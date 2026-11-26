"""Offline Notist integration tests: prepare once, build with different asset sources."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from test_items import export_fixture, item_fixture, items
from scripts.package_site import package


def fixture_site(root, manifest):
    """Small but complete relation/recipe/portrait/orchestrion fixture."""
    items.write_json(root / "sources/datamining.json", {
        "itemsSha256": manifest["itemsSha256"],
        "recipes": {"books": {"1": [[45, 2, 3]]},
                    "byResult": {"2": [[45, "刻木匠", 3, [[3, 4], [4, 1]]],
                                       [46, "裁衣匠", 1, [[5, 2], [3, 1]]]]}},
        "orchestrion": {"tracks": {"2": "music/test.scd"}},
        "portraits": {"kits": {"3": {"肖像": [["背景", "海岸", 190301]],
                                     "冒险者铭牌": [["底色", "蓝色", 193762]]}, "4": {}}},
    })
    items.write_json(root / "sources/reference.json", {"sets": {"groups": [["样例套装", [1, 8]]]}})
    items.write_json(root / "sources/model-library.json", {"items": {"1": "allSlots"}, "groups": [[1, 7]], "objects": []})


def shard(root, catalog, kind, index):
    return json.loads((root / "static" / catalog["assetPath"] / kind / f"{index}.json").read_text())


@unittest.skipUnless(os.environ.get("NOTIST_TEST_BIN"), "Set NOTIST_TEST_BIN to run the offline site fixture")
class OfflineSiteTests(unittest.TestCase):
    def test_prepare_once_then_build_disabled_and_shadow_cdn(self):
        repository = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ["modules", "templates", "static", "scripts"]:
                shutil.copytree(repository / name, root / name,
                                ignore=shutil.ignore_patterns("generated", "pipeline", "__pycache__", "model-sdk"))
            shutil.copy(repository / "Notist.toml", root)
            (root / "content").mkdir()
            (root / "content/index.md").write_text("# Test\n")
            bundle, manifest = export_fixture(root, [item_fixture(i, icon=12 if i % 2 else 0,
                                                                  searchCategory=0 if i == 2 else 4,
                                                                  untradable=i == 3) for i in range(1, 102)])
            fixture_site(root, manifest)

            # Prepare ONCE (pure manifest, no asset source needed).
            with patch.object(items, "ROOT", root):
                items.prepare(bundle)
                _, catalog = items.prepared_catalog()

            # Manifest shards contain pure integer icon IDs, never concrete URLs.
            recipes = shard(root, catalog, "recipes", 0)
            self.assertEqual(recipes["items"]["3"], ["物品 3", 12, "大斧"])
            relations = shard(root, catalog, "relations", 0)
            self.assertEqual([group[1] for group in relations],
                             ["同套装装备 · 样例套装", "同模型装备"])
            self.assertIn(["8", "物品 8"], [[row[0], row[1]] for row in relations[0][2]])

            # Build 1: assets disabled.
            env_disabled = dict(os.environ, GAME_ASSETS_SOURCE="disabled")
            result = subprocess.run([os.environ["NOTIST_TEST_BIN"], "build"], cwd=root, env=env_disabled,
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            output = root / "notist-output/icexiv-db"

            for page, prefix in [("items/1.html", "../"), ("items/index.html", "../"),
                                 ("items/page/2.html", "../../")]:
                html = (output / page).read_text()
                self.assertIn(f'src="{prefix}icon-placeholder.svg"', html)
                self.assertIn('loading="lazy"', html)
                self.assertIn('decoding="async"', html)
            book = (output / "items/1.html").read_text()
            self.assertIn('<notist-modules-game-recipe-panel', book)
            self.assertIn('notist-mode="book"', book)
            self.assertIn('notist-id="1"', book)
            self.assertIn('<notist-modules-game-actions', book)
            self.assertIn('src="../_notist/components.js"', book)
            self.assertTrue((output / "_notist/components.js").is_file())
            self.assertFalse((output / "_notist/pages").exists())
            self.assertIn("同套装装备 · 样例套装", book)
            self.assertNotIn('<notist-modules-game-model-viewer', book)
            self.assertNotIn('id="site-assets"', book)
            self.assertNotIn('<notist-modules-game-orchestrion-player', (output / "items/2.html").read_text())
            self.assertIn("暂无图片", (output / "items/3.html").read_text())

            # Package dual sites from disabled build.
            pages, cn = root / "pages", root / "cn"
            package(output, pages, cn)
            nested = Path("items/page/2.html")
            global_html = (pages / nested).read_text()
            domestic_html = (cn / nested).read_text()
            self.assertIn('href="../../site.css?v=', global_html)
            self.assertNotRegex(global_html, r'(?:href|src|action)="/(?!/)')
            self.assertNotIn("京ICP备", global_html)
            self.assertIn("京ICP备", domestic_html)
            self.assertIn('src="/_analytics/tracker.js"', domestic_html)
            self.assertTrue((cn / "police-beian.png").is_file())

            # Build 2: Remote logical-path CDN WITHOUT re-running prepare!
            cdn = "https://media.example/icexiv-db"
            env_cdn = dict(os.environ, GAME_ASSETS_SOURCE=cdn)
            result = subprocess.run([os.environ["NOTIST_TEST_BIN"], "build"], cwd=root, env=env_cdn,
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

            item1 = (output / "items/1.html").read_text()
            self.assertIn(f'src="{cdn}/icons/12.webp"', item1)
            self.assertIn('<notist-modules-game-model-viewer', item1)
            self.assertIn(f'notist-manifest="{cdn}/models/manifests/1.json"', item1)
            self.assertIn('id="site-assets"', item1)
            self.assertIn(cdn, item1)

            item2 = (output / "items/2.html").read_text()
            self.assertIn('<notist-modules-game-orchestrion-player', item2)
            self.assertIn(f'notist-audio="{cdn}/orchestrion/2.mp3"', item2)

            item3 = (output / "items/3.html").read_text()
            self.assertIn(f'src="{cdn}/portraits/190301.webp"', item3)
