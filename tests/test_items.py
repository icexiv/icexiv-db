import csv
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import tempfile
import struct
import zlib

spec = importlib.util.spec_from_file_location("items", Path(__file__).resolve().parents[1] / "scripts/items.py")
items = importlib.util.module_from_spec(spec)
spec.loader.exec_module(items)


def fixture(entries, headers=None):
    headers = headers or items.REQUIRED
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["key"] + list(range(len(headers) - 1)))
    writer.writerow(headers)
    writer.writerow(["int32"] + ["str"] * (len(headers) - 1))
    for entry in entries:
        writer.writerow([entry.get(key, "0") for key in headers])
    return output.getvalue().encode("utf-8-sig")


def icon_fixture(directory, source, icon_id=12):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00\x80")) + chunk(b"IEND", b""))
    directory.mkdir()
    (directory / f"{icon_id}.png").write_bytes(png)
    export = {"version": 1, "gameVersion": source["gameVersion"], "csvSha256": source["sha256"],
              "icons": {str(icon_id): {"status": "exported", "resource": "ui/icon/000000/000012.tex",
                                      "sha256": hashlib.sha256(png).hexdigest(), "width": 1, "height": 1}}}
    items.write_json(directory / "manifest.json", export)
    return export


class ItemTests(unittest.TestCase):
    def test_icon_request_deduplicates_ids_and_pins_input(self):
        raw = fixture([{"#": "1", "Name": "甲", "Icon": "12"},
                       {"#": "2", "Name": "乙", "Icon": "12"},
                       {"#": "3", "Name": "丙", "Icon": "0"}])
        source = {"sha256": hashlib.sha256(raw).hexdigest(), "gameVersion": "test"}
        with tempfile.TemporaryDirectory() as directory, patch.object(items, "manifest", return_value=source):
            root = Path(directory)
            (root / "Item.csv").write_bytes(raw)
            items.icon_request(root / "Item.csv", root / "request.json")
            self.assertEqual(json.loads((root / "request.json").read_text()), {
                "version": 1, "gameVersion": "test", "csvSha256": source["sha256"], "iconIds": [0, 12],
            })

    def test_icon_export_validation_and_missing_states(self):
        source = {"sha256": "a" * 64, "gameVersion": "test"}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "icons"
            export = icon_fixture(root, source)
            assets, digest = items.load_icons(root, source, [{"icon": 12}])
            self.assertEqual(assets[12], (root / "12.png").read_bytes())
            self.assertEqual(len(digest), 16)
            for status in ["failed", "unknown"]:
                export["icons"]["12"] = {"status": status}
                items.write_json(root / "manifest.json", export)
                with self.assertRaisesRegex(ValueError, "incomplete or failed"):
                    items.load_icons(root, source, [{"icon": 12}])
            export["icons"] = {"12": {"status": "missing"}, "0": {"status": "unconfigured"}}
            items.write_json(root / "manifest.json", export)
            self.assertEqual(items.load_icons(root, source, [{"icon": 12}, {"icon": 0}])[0], {})
            with self.assertRaisesRegex(ValueError, "incomplete or failed"):
                items.load_icons(root, source, [{"icon": 99}])

    def test_prepare_copies_verified_icons_and_preserves_export(self):
        raw = fixture([{"#": "1", "Name": "甲", "Icon": "12"},
                       {"#": "2", "Name": "乙", "Icon": "12"},
                       {"#": "3", "Name": "丙", "Icon": "0"}])
        source = {"sha256": hashlib.sha256(raw).hexdigest(), "gameVersion": "test"}
        with tempfile.TemporaryDirectory() as directory, patch.object(items, "ROOT", Path(directory)), patch.object(items, "manifest", return_value=source), patch.object(items, "source_url", return_value="https://example.com"):
            root = Path(directory)
            csv_path = root / "Item.csv"
            csv_path.write_bytes(raw)
            export = icon_fixture(root / "icons", source)
            export["icons"]["0"] = {"status": "unconfigured"}
            items.write_json(root / "icons/manifest.json", export)
            items.prepare(csv_path, root / "icons")
            config = json.loads((root / "data/catalog.json").read_text())
            assets = root / "static" / config["assetPath"]
            self.assertEqual(len(list((assets / "icons").glob("*.png"))), 1)
            index = json.loads((assets / "index.json").read_text())
            self.assertEqual(index[0][3], index[1][3])
            self.assertEqual(index[2][3], items.PLACEHOLDER)
            detail = json.loads((root / "content/.data/items/0.json").read_text())
            page = json.loads((root / "content/.data/catalog/page-1.json").read_text())
            self.assertEqual(detail[0][12], index[0][3])
            self.assertEqual(page["items"][0][3], index[0][3])
            marker = root / "static/generated/keep-on-error"
            marker.write_text("keep")
            # Reject corruption before replacing any generated namespace.
            (root / "icons/12.png").write_bytes(b"corrupt")
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                items.prepare(csv_path, root / "icons")
            self.assertTrue(marker.exists())
            with self.assertRaisesRegex(ValueError, "does not match"):
                items.load_icons(root / "icons", {**source, "gameVersion": "other"}, [{"icon": 12}])
            items.prepare(csv_path)
            self.assertTrue((root / "icons/manifest.json").exists())
            fallback = json.loads((root / "static" / json.loads((root / "data/catalog.json").read_text())["assetPath"] / "index.json").read_text())
            self.assertTrue(all(record[3] == items.PLACEHOLDER for record in fallback))

    def test_negative_and_overflowing_icon_ids_are_rejected(self):
        for icon in ["-1", str(2**32)]:
            with self.assertRaisesRegex(ValueError, "Invalid Icon ID"):
                items.parse_items(fixture([{"#": "1", "Name": "甲", "Icon": icon}]))

    def test_response_encoding_preserves_protocol_values_and_unicode(self):
        response = {"version": 1, "input": {"text": "<物品>\n\"反斜线\\", "values": [True, False, None, -(2**63), 2**64 - 1]}}
        output = io.StringIO()
        items.write_response(response, output)
        self.assertEqual(json.loads(output.getvalue()), response)
        self.assertIn("物品", output.getvalue())
        self.assertNotIn(": ", output.getvalue())
        self.assertFalse(output.getvalue().endswith("\n"))

    def test_extension_errors_still_use_the_response_protocol(self):
        output = io.StringIO()
        with patch("sys.argv", ["items.py", "extension"]), patch("sys.stdin", io.StringIO("{}")), patch("sys.stdout", output), patch.object(items, "extend", side_effect=ValueError("无效输入")):
            items.main()
        self.assertEqual(json.loads(output.getvalue()), {"version": 1, "errors": ["无效输入"]})

    def test_real_csv_quoting_and_boolean_formats(self):
        raw = fixture([{"#": "12", "Name": '<测试>,"物品"', "Description": "第一行\n第二行",
                        "IsUnique": "True", "IsUntradable": "0", "CanBeHq": "1"}])
        item, = items.parse_items(raw)
        self.assertEqual(item["name"], '<测试>,"物品"')
        self.assertEqual(item["description"], "第一行\n第二行")
        self.assertTrue(item["unique"])
        self.assertTrue(item["hq"])
        self.assertFalse(item["untradable"])

    def test_filters_empty_and_zero_and_sorts_ids(self):
        raw = fixture([{"#": "0", "Name": "空条目"}, {"#": "2", "Name": "乙"},
                       {"#": "1", "Name": "甲"}, {"#": "3", "Name": "  "}])
        self.assertEqual([i["id"] for i in items.parse_items(raw)], [1, 2])

    def test_duplicate_id_rejected(self):
        with self.assertRaisesRegex(ValueError, "Duplicate item ID"):
            items.parse_items(fixture([{"#": "1", "Name": "甲"}] * 2))

    def test_schema_change_rejected(self):
        with self.assertRaisesRegex(ValueError, "Missing or duplicate"):
            items.parse_items(fixture([], items.REQUIRED[:-1]))

    def test_wrong_header_rejected(self):
        with self.assertRaisesRegex(ValueError, "three-row"):
            items.parse_items(b"id,name\n1,test\n")

    def test_checksum(self):
        items.verify(b"test", {"sha256": hashlib.sha256(b"test").hexdigest()})
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            items.verify(b"wrong", {"sha256": hashlib.sha256(b"test").hexdigest()})

    def test_extension_generates_notc_pages_without_copying_item_data(self):
        raw = fixture([{"#": str(i), "Name": f"物品 {i}"} for i in range(1, 102)])
        source = {"sha256": hashlib.sha256(raw).hexdigest(), "gameVersion": "1.0"}
        request = {"version": 1, "stage": "prepare", "input": {
            "documents": {"index.not": "= Home"},
            "data": {"catalog": {
                "source": source, "pageCount": 2, "assetPath": "generated/hash",
                "pageSize": 100, "count": 101, "sourceUrl": "https://example.com/Item.csv",
            }, "unrelated": {"keep": True}},
        }}
        with tempfile.TemporaryDirectory() as directory, patch.object(items, "manifest", return_value=source):
            path = Path(directory) / "Item.csv"
            path.write_bytes(raw)
            response = items.extend(request, path)
        site = response["input"]
        self.assertEqual(len(site["documents"]), 104)
        self.assertEqual(site["documents"]["index.not"], "= Home")
        self.assertEqual(site["data"]["unrelated"], {"keep": True})
        self.assertNotIn("items", site["data"])
        self.assertNotIn("pages", site["data"]["catalog"])
        detail = site["documents"]["items/101.not"]
        self.assertTrue(detail.startswith('#import "../../modules/views.notc" as views;'))
        self.assertIn('#views.item(p"../.data/items/0.json", 100)', detail)
        self.assertNotIn("@!(", detail)
        first = site["documents"]["items/index.not"]
        self.assertIn('#views.catalog(p"../.data/catalog/page-1.json")', first)
        second = site["documents"]["items/page/2.not"]
        self.assertTrue(second.startswith('#import "../../../modules/views.notc" as views;'))
        self.assertIn('#views.catalog(p"../../.data/catalog/page-2.json")', second)

    def test_item_record_is_ready_for_notc(self):
        item = {
            "id": 7, "name": "甲", "description": "说明", "category": 3,
            "searchCategory": 4, "equipLevel": 5, "rarity": 6, "stackSize": 99,
            "unique": True, "untradable": False, "hq": True, "icon": 12,
        }
        self.assertEqual(items.item_record(item), [
            "7", "甲", "说明", "3", "4", "5", "6", "99", "是", "否", "是", "12", items.PLACEHOLDER,
        ])

    def test_catalog_pages_encode_page_navigation(self):
        records = [{"id": i, "name": f"物品 {i}", "category": 0} for i in range(1, 102)]
        source = {"gameVersion": "1.0"}
        with patch.object(items, "source_url", return_value="https://example.com/Item.csv"):
            pages = items.catalog_pages(records, source)
        self.assertEqual(len(pages), 2)
        self.assertEqual(pages[0]["count"], 101)
        self.assertEqual(pages[0]["version"], "1.0")
        self.assertEqual(pages[0]["sourceUrl"], "https://example.com/Item.csv")
        self.assertEqual(pages[0]["label"], "第 1 / 2 页")
        self.assertEqual(pages[0]["previous"], "")
        self.assertEqual(pages[0]["next"], "/items/page/2.html")
        self.assertEqual(pages[0]["items"][0], ["1", "物品 1", "0", items.PLACEHOLDER])
        self.assertEqual(len(pages[1]["items"]), 1)
        self.assertEqual(pages[1]["previous"], "/items/index.html")
        self.assertEqual(pages[1]["next"], "")

    def test_extension_does_not_overwrite_handwritten_pages(self):
        raw = fixture([{"#": "1", "Name": "物品"}])
        source = {"sha256": hashlib.sha256(raw).hexdigest()}
        request = {"version": 1, "stage": "prepare", "input": {
            "documents": {"items/1.not": "handwritten"},
            "data": {"catalog": {"source": source, "pageCount": 1}},
        }}
        with tempfile.TemporaryDirectory() as directory, patch.object(items, "manifest", return_value=source):
            path = Path(directory) / "Item.csv"
            path.write_bytes(raw)
            with self.assertRaisesRegex(ValueError, "conflicts"):
                items.extend(request, path)

    def test_wrong_extension_protocol_rejected(self):
        with self.assertRaisesRegex(ValueError, "protocol"):
            items.extend({"version": 2}, Path("nonexistent"))


if __name__ == "__main__":
    unittest.main()
