"""Optional offline Notist integration using newly authored CSV/PNG fixtures."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from test_items import fixture, icon_fixture, items


@unittest.skipUnless(os.environ.get("NOTIST_TEST_BIN"), "Set NOTIST_TEST_BIN to run the offline site fixture")
class IconSiteTests(unittest.TestCase):
    def test_static_detail_and_both_catalog_depths_reference_published_icons(self):
        repository = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ["modules", "templates", "static", "scripts"]:
                shutil.copytree(repository / name, root / name,
                                ignore=shutil.ignore_patterns("generated", "__pycache__"))
            shutil.copy(repository / "Notist.toml", root)
            (root / "content").mkdir()
            (root / "content/index.not").write_text("= Test\n")
            raw = fixture([{"#": str(i), "Name": f"物品 {i}", "Icon": "12" if i % 2 else "0"}
                           for i in range(1, 102)])
            source = {"sha256": hashlib.sha256(raw).hexdigest(), "gameVersion": "synthetic",
                      "repository": "example/test", "commit": "test", "path": "Item.csv"}
            items.write_json(root / "sources/item.json", source)
            (root / "inputs").mkdir()
            (root / "inputs/Item.csv").write_bytes(raw)
            export = icon_fixture(root / "icons", source)
            export["icons"]["0"] = {"status": "unconfigured"}
            items.write_json(root / "icons/manifest.json", export)
            with patch.object(items, "ROOT", root):
                items.prepare(root / "inputs/Item.csv", root / "icons")
            result = subprocess.run([os.environ["NOTIST_TEST_BIN"], "build"], cwd=root,
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            output = root / "dist/icexiv-db"
            catalog = json.loads((root / "data/catalog.json").read_text())
            icon_path = catalog["assetPath"] + "/icons/12.png"
            for page, prefix in [("items/1.html", "../"), ("items/index.html", "../"),
                                 ("items/page/2.html", "../../")]:
                html = (output / page).read_text()
                self.assertIn(f'src="{prefix}{icon_path}"', html)
                self.assertIn('loading="lazy"', html)
                self.assertIn('width="32" height="32"', html)
            self.assertIn('src="../icon-placeholder.svg"', (output / "items/2.html").read_text())
            self.assertEqual((output / icon_path).read_bytes(), (root / "icons/12.png").read_bytes())
