"""The CSV path: datamining tables in, the same site manifest out."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import items
from scripts.pipeline import bundle, manifest

HEADER = {
    "#": "#", "Name": "Name", "Description": "Description", "Icon": "Icon",
    "ItemUICategory": "ItemUICategory", "ItemSearchCategory": "ItemSearchCategory",
    "Level{Equip}": "Level{Equip}", "Rarity": "Rarity", "StackSize": "StackSize",
    "IsUnique": "IsUnique", "IsUntradable": "IsUntradable", "CanBeHq": "CanBeHq",
    "EquipSlotCategory": "EquipSlotCategory", "ItemAction": "ItemAction",
}
ROWS = [
    [1, "物品 1", "说明", 12, 3, 4, 5, 1, 99, "False", "False", "True", 0, 1],
    [2, "物品 2", "", 0, 3, 0, 1, 1, 999, "True", "True", "False", 0, 1],
    [0, "", "", 0, 0, 0, 0, 0, 0, "False", "False", "False", 0, 0],
]


def write_item_csv(directory):
    names = list(HEADER.values())
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "Item.csv"
    path.write_text(
        "key," + ",".join(str(i) for i in range(len(names))) + "\n"
        + ",".join(names) + "\n"
        + ",".join("str" for _ in names) + "\n"
        + "\n".join(",".join(map(str, row)) for row in ROWS) + "\n",
        encoding="utf-8")
    (directory / "ItemAction.csv").write_text(
        "key,0,1,2\n#,Type,Data[0],Data[1]\nstr,str,str,str\n1,0,0,0\n",
        encoding="utf-8")
    return path


class ManifestTests(unittest.TestCase):
    def test_from_csv_writes_the_same_manifest_shape(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_item_csv(root / "csv")
            output = root / "export"
            manifest.build_manifest(root / "csv", output, commit="0123456789abcdef", snapshots=False)
            data = json.loads((output / "manifest.json").read_bytes())
            records = json.loads((output / "items.json").read_bytes())
            self.assertEqual(data["version"], 2)
            self.assertEqual(data["source"]["kind"], "datamining")
            self.assertEqual(data["source"]["commit"], "0123456789abcdef")
            self.assertEqual(data["itemCount"], 2)
            self.assertEqual(set(data["source"]["files"]), {"Item.csv", "ItemAction.csv"})
            self.assertEqual([record["id"] for record in records], [1, 2])
            self.assertEqual(records[0], {
                "id": 1, "name": "物品 1", "description": "说明", "icon": 12, "category": 3,
                "searchCategory": 4, "equipLevel": 5, "rarity": 1, "stackSize": 99,
                "unique": False, "untradable": False, "hq": True})
            self.assertEqual(records[1]["hq"], False)
            # The site loader accepts the manifest without any PNG icons.
            export, loaded, _ = items.load_export(output)
            self.assertEqual(export["source"]["kind"], "datamining")
            self.assertEqual(len(loaded), 2)

    def test_from_csv_writes_the_datamining_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_item_csv(root / "csv")
            target = root / "sources/datamining.json"
            with patch.object(bundle, "DATAMINING", target):
                manifest.build_manifest(root / "csv", root / "export", commit="abc")
            data = json.loads(target.read_bytes())
            self.assertEqual(data["source"]["commit"], "abc")
            self.assertEqual(data["source"]["kind"], "datamining")
            self.assertEqual(data["itemsSha256"], items.sha256((root / "export/items.json").read_bytes()))
            self.assertIn("unlocks", data)
            self.assertNotIn("itemsSha256", data["unlocks"])
            self.assertNotIn("recipes", data)

    def test_datamining_manifest_requires_its_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_item_csv(root / "csv")
            manifest.build_manifest(root / "csv", root / "export", commit="abc", snapshots=False)
            path = root / "export/manifest.json"
            for broken in [
                json.loads(path.read_bytes()) | {"source": {"kind": "datamining"}},
                json.loads(path.read_bytes()) | {"source": {"kind": "game", "gameVersion": "x", "commit": "y", "files": {"a": "b"}}},
                json.loads(path.read_bytes()) | {"version": 3},
            ]:
                path.write_text(json.dumps(broken))
                with self.assertRaises(ValueError):
                    items.load_export(root / "export")

    def test_prepare_runs_without_icons_or_pillow(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_item_csv(root / "csv")
            manifest.build_manifest(root / "csv", root / "export", commit="abc", snapshots=False)
            with patch.object(items, "ROOT", root):
                items.prepare(root / "export")
                _, catalog = items.prepared_catalog()
            records = json.loads((root / "content/.data/items/0.json").read_text())
            self.assertEqual([record["icon"] for record in records], ["12", "0"])
            index = json.loads((root / "static" / catalog["assetPath"] / "index.json").read_text())
            self.assertEqual([row[3] for row in index], [12, 0])
            self.assertTrue((root / "content/.data/prepared.json").is_file())


if __name__ == "__main__":
    unittest.main()
