import copy
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import items


def item_fixture(item_id=1, **values):
    return dict(id=item_id, name=f"物品 {item_id}", description="说明", icon=12, category=3,
                searchCategory=4, equipLevel=5, rarity=1, stackSize=99,
                unique=False, untradable=False, hq=True) | values


def fixture(records):
    return json.dumps(records, ensure_ascii=False).encode()


def export_fixture(root, records=None):
    records = [item_fixture()] if records is None else records
    directory = root / "inputs/game-export"
    items.write_json(directory / "items.json", records)
    source = {
        "kind": "datamining",
        "gameVersion": "synthetic",
        "language": "chs",
        "commit": "0123456789abcdef",
        "files": {"Item.csv": "a" * 64},
    }
    manifest = {
        "version": 2,
        "source": source,
        "itemCount": len(records),
        "itemsSha256": items.sha256((directory / "items.json").read_bytes()),
    }
    items.write_json(directory / "manifest.json", manifest)
    return directory, manifest


class ItemTests(unittest.TestCase):
    def test_json_preserves_text_and_sorts_ids(self):
        records = items.parse_items(fixture([item_fixture(2), item_fixture(1, name='<测试>,"物品"', description="一\n二")]))
        self.assertEqual([r["id"] for r in records], [1, 2])
        self.assertEqual(records[0]["description"], "一\n二")
        self.assertEqual(records[0]["name"], '<测试>,"物品"')

    def test_invalid_fields_duplicates_and_filtered_rows_rejected(self):
        for key, value in [("icon", -1), ("icon", 2**32), ("id", True), ("id", 0),
                           ("name", " "), ("hq", 1), ("unique", "false"), ("description", None)]:
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                items.parse_items(fixture([item_fixture(**{key: value})]))
        with self.assertRaisesRegex(ValueError, "Duplicate item ID"):
            items.parse_items(fixture([item_fixture(), item_fixture()]))
        with self.assertRaisesRegex(ValueError, "nonempty"):
            items.parse_items(b"[]")

    def test_bundle_identity_count_and_item_hash_are_checked(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(items, "ROOT", Path(directory)):
            path, manifest = export_fixture(Path(directory))
            self.assertEqual(len(items.load_export(path)[1]), 1)
            variants = []
            for key, value in [("gameVersion", ""), ("commit", ""), ("kind", "other"), ("files", {})]:
                invalid = copy.deepcopy(manifest)
                invalid["source"][key] = value
                variants.append(invalid)
            variants.extend([manifest | {"itemCount": 2}, manifest | {"itemsSha256": "bad"}, manifest | {"version": 9}])
            for invalid in variants:
                items.write_json(path / "manifest.json", invalid)
                with self.assertRaises(ValueError):
                    items.load_export(path)

    def test_prepare_is_pure_manifest_and_extension_resolves_assets(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(items, "ROOT", Path(directory)):
            root = Path(directory)
            path, _ = export_fixture(root, [item_fixture(i, icon=12 if i % 2 else 0) for i in range(1, 102)])
            items.prepare(path)
            _, catalog = items.prepared_catalog()
            assets = root / "static" / catalog["assetPath"]
            index = json.loads((assets / "index.json").read_text())
            self.assertEqual(index[0][3], 12)
            self.assertEqual(index[1][3], 0)
            records = json.loads((root / "content/.data/items/0.json").read_text())
            pages = json.loads((root / "content/.data/catalog/page-1.json").read_text())
            self.assertEqual(records[0]["icon"], "12")
            self.assertNotIn("iconUrl", records[0])
            self.assertEqual(pages["items"][0][3], "12")
            self.assertEqual(records[0]["kind"], "大斧")
            request = {"version": 2, "event": "before_compile",
                       "documents": {"index.md": "# Home"}}
            state = {}
            with patch.dict(os.environ, GAME_ASSETS_SOURCE="disabled"):
                response = items.extend(copy.deepcopy(request), path, state=state)
            documents = response["documents"]
            self.assertEqual(len(documents), 104)
            self.assertIn('#views.item("../.data/items/0.json", 100)', documents["items/101.md"])
            self.assertIn('#views.catalog("../../.data/catalog/page-2.json")', documents["items/page/2.md"])
            self.assertNotIn("data", response)
            template = {"version": 2, "event": "before_template", "pages": [],
                        "data": {"catalog": {"stale": True}, "other": True}}
            tpl_out = items.extend(template, path, state=state)
            self.assertEqual(tpl_out["version"], 2)
            self.assertEqual(tpl_out["event"], "before_template")
            self.assertEqual(tpl_out["data"]["catalog"], catalog)
            self.assertTrue(tpl_out["data"]["other"])
            self.assertRegex(tpl_out["data"]["asset_rev"], r"^[a-f0-9]{10}$")
            self.assertTrue(template["data"]["other"])
            self.assertEqual(template["data"]["catalog"], {"stale": True})
            request["documents"]["items/1.md"] = "# handwritten"
            with self.assertRaisesRegex(ValueError, "conflicts"):
                items.extend(request, path)
            items.write_json(root / "content/.data/prepared.json", {"exportSha256": "bad"})
            with self.assertRaisesRegex(ValueError, "prepare before"):
                items.extend(request, path)

    def test_extension_state_is_build_local_and_committed_only_on_success(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(items, "ROOT", Path(directory)):
            path, _ = export_fixture(Path(directory))
            items.prepare(path)
            state = {}
            template = {"version": 2, "event": "before_template", "data": {"other": True}}
            with self.assertRaisesRegex(ValueError, "before_compile"):
                items.extend(template, path, state=state)
            compile_request = {"version": 2, "event": "before_compile", "documents": {"index.md": "# Home"}}
            with patch.dict(os.environ, GAME_ASSETS_SOURCE="disabled"):
                items.extend(compile_request, path, state=state)
            self.assertEqual(compile_request["documents"], {"index.md": "# Home"})
            # before_template uses the in-memory build snapshot, not another disk read.
            (path / "manifest.json").unlink()
            response = items.extend(template, path, state=state)
            self.assertEqual(response["data"]["catalog"]["count"], 1)
            (Path(directory) / "content/.data/catalog.json").unlink()
            with self.assertRaisesRegex(ValueError, "prepare before"):
                items.extend(compile_request, path, state=state)
            self.assertEqual(state, {})

    def test_preparation_receipt_is_required_and_written_last(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(items, "ROOT", Path(directory)):
            root = Path(directory)
            path, _ = export_fixture(root)
            with self.assertRaisesRegex(ValueError, "prepare before"):
                items.prepared_catalog()
            items.prepare(path)
            with patch.object(items, "write_json", side_effect=OSError("disk full")):
                with self.assertRaisesRegex(OSError, "disk full"):
                    items.prepare(path)
            self.assertFalse((root / "content/.data/prepared.json").exists())
            with self.assertRaisesRegex(ValueError, "prepare before"):
                items.prepared_catalog()

    def test_item_record_shape_and_pagination(self):
        record = item_fixture(7)
        self.assertEqual(items.category_name(record), "大斧")
        pages = items.catalog_pages([item_fixture(i) for i in range(1, 102)], {"gameVersion": "test"})
        self.assertEqual(pages[0]["previous"], "")
        self.assertEqual(pages[0]["next"], "/items/page/2.html")
        self.assertEqual(pages[1]["previous"], "/items/index.html")
        self.assertEqual(pages[1]["next"], "")
        self.assertEqual(len(pages[1]["items"]), 1)

    def test_protocol_preserves_unicode_and_reports_errors(self):
        output = io.StringIO()
        response = {"version": 2, "event": "before_compile", "documents": {"test.md": "# <物品>\n"}}
        items.write_response(response, output)
        self.assertEqual(json.loads(output.getvalue()), response)
        self.assertIn("物品", output.getvalue())
        self.assertTrue(output.getvalue().endswith("\n"))
        with self.assertRaisesRegex(ValueError, "protocol"):
            items.extend({"version": 1}, Path("nonexistent"))
        with self.assertRaisesRegex(ValueError, "event"):
            items.extend({"version": 2, "event": "prepare"}, Path("nonexistent"))
        output = io.StringIO()
        with patch("sys.argv", ["items.py", "extension"]), patch("sys.stdin", io.StringIO("{}")), patch("sys.stdout", output):
            items.main()
        self.assertIn("errors", json.loads(output.getvalue()))


if __name__ == "__main__":
    unittest.main()
