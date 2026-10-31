import csv
import hashlib
import importlib.util
import io
from pathlib import Path
import unittest
from unittest.mock import patch
import tempfile

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


class ItemTests(unittest.TestCase):
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

    def test_extension_generates_static_details_and_pagination(self):
        raw = fixture([{"#": str(i), "Name": f"物品 {i}"} for i in range(1, 102)])
        source = {"sha256": hashlib.sha256(raw).hexdigest()}
        request = {"version": 1, "stage": "prepare", "input": {
            "documents": {"index.not": "= Home"},
            "data": {"catalog": {"source": source}, "unrelated": {"keep": True}},
        }}
        with tempfile.TemporaryDirectory() as directory, patch.object(items, "manifest", return_value=source):
            path = Path(directory) / "Item.csv"
            path.write_bytes(raw)
            response = items.extend(request, path)
        site = response["input"]
        self.assertEqual(len(site["documents"]), 104)
        self.assertEqual(site["documents"]["index.not"], "= Home")
        self.assertEqual(site["data"]["unrelated"], {"keep": True})
        self.assertIn('item_id: "101"', site["documents"]["items/101.not"])
        pages = site["data"]["catalog"]["pages"]
        self.assertEqual(len(pages["1"]["items"]), 100)
        self.assertEqual(len(pages["2"]["items"]), 1)
        self.assertEqual(pages["1"]["next"], "items/page/2.html")
        self.assertEqual(pages["2"]["previous"], "items/index.html")
        self.assertIsNone(pages["2"]["next"])

    def test_extension_does_not_overwrite_handwritten_pages(self):
        raw = fixture([{"#": "1", "Name": "物品"}])
        source = {"sha256": hashlib.sha256(raw).hexdigest()}
        request = {"version": 1, "stage": "prepare", "input": {
            "documents": {"items/1.not": "handwritten"},
            "data": {"catalog": {"source": source}},
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
