import copy
import importlib.util
import io
import json
from pathlib import Path
import selectors
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zlib

spec = importlib.util.spec_from_file_location("items", Path(__file__).resolve().parents[1] / "scripts/items.py")
items = importlib.util.module_from_spec(spec)
spec.loader.exec_module(items)


def item_fixture(item_id=1, **values):
    return dict(id=item_id, name=f"物品 {item_id}", description="说明", icon=12, category=3,
                searchCategory=4, equipLevel=5, rarity=1, stackSize=99,
                unique=False, untradable=False, hq=True) | values


def fixture(records):
    return json.dumps(records, ensure_ascii=False).encode()


def export_fixture(root, records=None):
    records = [item_fixture()] if records is None else records
    schema = {"version": 1, "gameVersion": "synthetic", "language": "chs", "exhSha256": "a" * 64, "fields": {}}
    items.write_json(root / "sources/item-schema.json", schema)
    schema_bytes = (root / "sources/item-schema.json").read_bytes()
    directory = root / "inputs/game-export"
    items.write_json(directory / "items.json", records)
    source = {"kind": "game", "gameVersion": "synthetic", "language": "chs",
              "schemaSha256": items.sha256(schema_bytes), "resources": {"exd/item.exh": "a" * 64}}
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(b"\0\xff\0\0\x80")) + chunk(b"IEND", b""))
    icons = {}
    for icon_id in {record["icon"] for record in records}:
        if icon_id == 0:
            icons["0"] = {"status": "unconfigured"}
        else:
            path = directory / "icons" / f"{icon_id}.png"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(png)
            icons[str(icon_id)] = {"status": "exported", "resource": f"ui/icon/000000/{icon_id:06}.tex",
                                   "sha256": items.sha256(png), "width": 1, "height": 1}
    manifest = {"version": 1, "source": source, "itemCount": len(records),
                "itemsSha256": items.sha256((directory / "items.json").read_bytes()),
                "textMacros": {}, "icons": icons}
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

    def test_bundle_schema_count_and_item_hash_are_checked(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(items, "ROOT", Path(directory)):
            path, manifest = export_fixture(Path(directory))
            self.assertEqual(len(items.load_export(path)[1]), 1)
            variants = []
            for key, value in [("gameVersion", "wrong"), ("schemaSha256", "b" * 64), ("kind", "other")]:
                invalid = copy.deepcopy(manifest)
                invalid["source"][key] = value
                variants.append(invalid)
            variants.extend([manifest | {"itemCount": 2}, manifest | {"itemsSha256": "bad"}])
            for invalid in variants:
                items.write_json(path / "manifest.json", invalid)
                with self.assertRaises(ValueError):
                    items.load_export(path)

    def test_icon_failures_missing_and_corruption_are_distinct(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(items, "ROOT", Path(directory)):
            path, manifest = export_fixture(Path(directory), [item_fixture(), item_fixture(2, icon=0)])
            invalid = copy.deepcopy(manifest)
            invalid["icons"]["12"] = {"status": "failed", "error": "bad data"}
            items.write_json(path / "manifest.json", invalid)
            with self.assertRaisesRegex(ValueError, "failed export"):
                items.load_export(path)
            invalid["icons"]["12"] = {"status": "missing"}
            items.write_json(path / "manifest.json", invalid)
            self.assertEqual(items.load_export(path)[2], {})
            del invalid["icons"]["12"]
            items.write_json(path / "manifest.json", invalid)
            with self.assertRaisesRegex(ValueError, "icon ID set"):
                items.load_export(path)
            items.write_json(path / "manifest.json", manifest)
            (path / "icons/12.png").write_bytes(b"bad")
            with self.assertRaisesRegex(ValueError, "PNG SHA-256"):
                items.load_export(path)

    def test_prepare_and_extension_share_identity_and_icon_urls(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(items, "ROOT", Path(directory)):
            root = Path(directory)
            path, manifest = export_fixture(root, [item_fixture(i, icon=12 if i % 2 else 0) for i in range(1, 102)])
            items.prepare(path)
            _, catalog = items.prepared_catalog(path)
            self.assertFalse((root / "data/catalog.json").exists())
            assets = root / "static" / catalog["assetPath"]
            index = json.loads((assets / "index.json").read_text())
            self.assertEqual(index[0][3], f"/{catalog['assetPath']}/icons/12.png")
            self.assertEqual(index[1][3], items.PLACEHOLDER)
            self.assertEqual(len(list((assets / "icons").glob("*.png"))), 1)
            records = json.loads((root / "content/.data/items/0.json").read_text())
            pages = json.loads((root / "content/.data/catalog/page-1.json").read_text())
            self.assertEqual(records[0][12], index[0][3])
            self.assertEqual(pages["items"][0][3], index[0][3])
            request = {"version": 2, "event": "before_compile",
                       "documents": {"index.md": "# Home"}}
            state = {}
            response = items.extend(copy.deepcopy(request), path, state=state)
            documents = response["documents"]
            self.assertEqual(len(documents), 104)
            self.assertIn('#views.item("../.data/items/0.json", 100)', documents["items/101.md"])
            self.assertIn('#views.catalog("../../.data/catalog/page-2.json")', documents["items/page/2.md"])
            self.assertNotIn("data", response)
            template = {"version": 2, "event": "before_template", "pages": [],
                         "data": {"catalog": {"stale": True}, "other": True}}
            self.assertEqual(items.extend(template, path, state=state), {
                "version": 2, "event": "before_template", "data": {"catalog": catalog, "other": True}})
            self.assertTrue(template["data"]["other"])
            self.assertEqual(template["data"]["catalog"], {"stale": True})
            request["documents"]["items/1.md"] = "# handwritten"
            with self.assertRaisesRegex(ValueError, "conflicts"):
                items.extend(request, path)
            items.write_json(root / "content/.data/prepared.json", {"exportSha256": "bad"})
            with self.assertRaisesRegex(ValueError, "prepare before"):
                items.extend(request, path)
            marker = root / "static/generated/keep-on-error"
            marker.write_text("keep")
            (path / "icons/12.png").write_bytes(b"corrupt")
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                items.prepare(path)
            self.assertTrue(marker.exists())
            self.assertTrue((path / "manifest.json").exists())

    def test_extension_state_is_build_local_and_committed_only_on_success(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(items, "ROOT", Path(directory)):
            path, _ = export_fixture(Path(directory))
            items.prepare(path)
            state = {}
            template = {"version": 2, "event": "before_template", "data": {"other": True}}
            with self.assertRaisesRegex(ValueError, "before_compile"):
                items.extend(template, path, state=state)
            compile_request = {"version": 2, "event": "before_compile", "documents": {"index.md": "# Home"}}
            items.extend(compile_request, path, state=state)
            self.assertEqual(compile_request["documents"], {"index.md": "# Home"})
            # The second event uses the validated build snapshot, not another disk read.
            (path / "manifest.json").unlink()
            response = items.extend(template, path, state=state)
            self.assertEqual(response["data"]["catalog"]["count"], 1)
            with self.assertRaises(FileNotFoundError):
                items.extend(compile_request, path, state=state)
            self.assertEqual(state, {})

    def test_preparation_receipt_is_required_and_written_last(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(items, "ROOT", Path(directory)):
            root = Path(directory)
            path, _ = export_fixture(root)
            with self.assertRaisesRegex(ValueError, "prepare before"):
                items.prepared_catalog(path)
            items.prepare(path)
            with patch.object(items, "write_json", side_effect=OSError("disk full")):
                with self.assertRaisesRegex(OSError, "disk full"):
                    items.prepare(path)
            self.assertFalse((root / "content/.data/prepared.json").exists())
            with self.assertRaisesRegex(ValueError, "prepare before"):
                items.prepared_catalog(path)

    def test_item_record_and_pagination(self):
        record = item_fixture(7)
        self.assertEqual(items.item_record(record), ["7", "物品 7", "说明", "3", "4", "5", "1", "99", "否", "否", "是", "12", items.PLACEHOLDER])
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

    def test_command_responds_to_each_event_before_eof(self):
        repository = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "scripts").mkdir()
            script = root / "scripts/items.py"
            script.write_bytes((repository / "scripts/items.py").read_bytes())
            (root / "scripts/categories.json").write_bytes((repository / "scripts/categories.json").read_bytes())
            with patch.object(items, "ROOT", root):
                bundle, _ = export_fixture(root)
                items.prepare(bundle)
            with subprocess.Popen([sys.executable, str(script), "extension"], cwd=root,
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True) as process:
                try:
                    with selectors.DefaultSelector() as selector:
                        selector.register(process.stdout, selectors.EVENT_READ)
                        for request in [
                            {"version": 2, "event": "before_compile", "documents": {"index.md": "# 物品"}},
                            {"version": 2, "event": "before_template", "pages": [], "data": {"other": True}},
                        ]:
                            process.stdin.write(json.dumps(request) + "\n")
                            process.stdin.flush()
                            self.assertTrue(selector.select(timeout=5), "Response must flush before stdin EOF")
                            line = process.stdout.readline()
                            self.assertTrue(line.endswith("\n"))
                            response = json.loads(line)
                            self.assertEqual(response["version"], 2)
                            self.assertEqual(response["event"], request["event"])
                            self.assertNotIn("errors", response)
                            if request["event"] == "before_compile":
                                self.assertIn("items/1.md", response["documents"])
                                self.assertEqual(response["documents"]["index.md"], "# 物品")
                                self.assertNotIn("data", response)
                            else:
                                self.assertTrue(response["data"]["other"])
                                self.assertEqual(response["data"]["catalog"]["count"], 1)
                                self.assertEqual(response["data"]["catalog"]["source"]["gameVersion"], "synthetic")
                    process.stdin.close()
                    self.assertEqual(process.wait(timeout=5), 0, process.stderr.read())
                    self.assertEqual(process.stdout.read(), "")
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.wait()


if __name__ == "__main__":
    unittest.main()
