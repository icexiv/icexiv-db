"""Optional offline Notist integration using newly authored game export fixtures."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from test_items import export_fixture, item_fixture, items
from scripts.package_site import package


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
            (root / "content/index.md").write_text("# Test\n")
            bundle, _ = export_fixture(root, [item_fixture(i, icon=12 if i % 2 else 0) for i in range(1, 102)])
            with patch.object(items, "ROOT", root):
                items.prepare(bundle)
            self.assertFalse((root / "data/catalog.json").exists())
            result = subprocess.run([os.environ["NOTIST_TEST_BIN"], "build"], cwd=root,
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            output = root / "notist-output/icexiv-db"
            with patch.object(items, "ROOT", root):
                _, catalog = items.prepared_catalog(bundle)
            icon_path = catalog["assetPath"] + "/icons/12.png"
            for page, prefix in [("items/1.html", "../"), ("items/index.html", "../"),
                                 ("items/page/2.html", "../../")]:
                html = (output / page).read_text()
                self.assertIn(f'src="{prefix}{icon_path}"', html)
                self.assertIn('loading="lazy"', html)
                self.assertIn('width="32" height="32"', html)
            self.assertIn('src="../icon-placeholder.svg"', (output / "items/2.html").read_text())
            self.assertEqual((output / icon_path).read_bytes(), (bundle / "icons/12.png").read_bytes())
            self.assertNotIn("CSV", (output / "items/index.html").read_text())
            self.assertNotIn("datamining", (output / "items/1.html").read_text())
            self.assertIn("客户端 synthetic", (output / "items/1.html").read_text())
            self.assertIn(f'data-index-url="../{catalog["assetPath"]}/index.json"',
                          (output / "items/index.html").read_text())
            pages, cn = root / "pages", root / "cn"
            package(output, pages, cn)
            nested = Path("items/page/2.html")
            global_html = (pages / nested).read_text()
            domestic_html = (cn / nested).read_text()
            self.assertIn('href="../../site.css"', global_html)
            self.assertNotRegex(global_html, r'(?:href|src|action)="/(?!/)')
            self.assertNotIn("京ICP备", global_html)
            self.assertFalse((pages / "_analytics").exists())
            self.assertIn("京ICP备", domestic_html)
            self.assertIn('src="/_analytics/tracker.js"', domestic_html)
            self.assertTrue((cn / "police-beian.png").is_file())
