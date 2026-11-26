import hashlib
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from scripts.media import EFFECT_SDK, SDK_FILES, install_sdk
from scripts.pipeline.model_library import ANIMATION_RECORD, animation_paths
from test_items import export_fixture, items


class ActionSnapshotTests(unittest.TestCase):
    def test_emote_items_resolve_through_item_action_and_timeline_rows(self):
        from scripts.pipeline.action_snapshot import build
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def sheet(name, columns, rows):
                path = root / name
                path.write_text("key," + ",".join(map(str, range(len(columns)))) + "\n"
                                + ",".join(columns) + "\n" + ",".join(["str"] * len(columns)) + "\n"
                                + "\n".join(",".join(map(str, row)) for row in rows) + "\n", encoding="utf-8")
                return path
            items_csv = sheet("Item.csv", ["#", "Name", "ItemAction"], [[12040, "演技教材·火盆舞", 724], [2, "普通物品", 1]])
            actions = sheet("ItemAction.csv", ["#", "Type", "Data[0]", "Data[1]", "Data[2]"],
                            [[724, 2633, 0, 5211, 98]])
            emotes = sheet("Emote.csv", ["#", "ActionTimeline[0]", "ActionTimeline[1]"], [[98, 3138, 3137]])
            timelines = sheet("ActionTimeline.csv", ["#", "Key"], [[3138, "emote/j_pose02_loop"], [3137, "emote/j_pose02_start"]])
            exported = root / "items.json"
            exported.write_text(json.dumps([{"id": 12040}, {"id": 2}]), encoding="utf-8")
            result = build(items_csv, actions, emotes, timelines, exported)
            self.assertEqual(result["items"], {"12040": {"emote": "98", "timelines": [
                ["3138", "emote/j_pose02_loop"], ["3137", "emote/j_pose02_start"]]}})


class AnimationTests(unittest.TestCase):
    def test_gear_uses_its_clade_skeleton_and_shared_idle_clip(self):
        self.assertEqual(animation_paths("armor", ["chara/equipment/e0968/model/c0201e0968_top.mdl"]), (
            "chara/human/c0201/skeleton/base/b0001/skl_c0201b0001.sklb",
            "chara/human/c0201/animation/a0001/bt_common/resident/idle.pap"))
        self.assertEqual(ANIMATION_RECORD, "cbnm_id0")
        self.assertIsNone(animation_paths("weapon", ["chara/weapon/w5004/obj/body/b0008/model/w5004b0008.mdl"]))
        self.assertIsNone(animation_paths("armor", ["chara/monster/m0994/obj/body/b0001/model/m0994b0001.mdl"]))


class MediaTests(unittest.TestCase):
    def test_extension_switches_asset_sources_without_rerunning_prepare(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle, export = export_fixture(root)
            digest = export["itemsSha256"]
            body = "a" * 64
            items.write_json(root / "sources/datamining.json", {
                "itemsSha256": digest,
                "portraits": {"kits": {"1": {"肖像": [["背景", "样例", 42]]}}},
                "orchestrion": {"tracks": {"1": "music/test.scd"}}})
            items.write_json(root / "sources/model-library.json",
                             {"itemsSha256": digest, "items": {"1": "allSlots"}, "objects": [body]})

            with patch.object(items, "ROOT", root):
                items.prepare(bundle)
                req = {"version": 2, "event": "before_compile", "documents": {"index.md": "# Home"}}
                tpl = {"version": 2, "event": "before_template", "pages": [], "data": {}}

                # 1. Disabled mode
                state = {}
                with patch.dict(os.environ, GAME_ASSETS_SOURCE="disabled"):
                    comp = items.extend(req, bundle, state=state)
                    out = items.extend(tpl, bundle, state=state)
                self.assertFalse((root / "content/.data/runtime-assets.json").exists())
                self.assertEqual(
                    json.loads(comp["data_files"][".data/runtime-assets.json"]),
                    {"icons": "", "portraits": "", "orchestrion": "", "models": ""},
                )
                self.assertNotIn("assets", out["data"])

                # 2. Local mode (all 4 kinds via `just serve-assets` on 127.0.0.1:8015)
                state = {}
                with patch.dict(os.environ, GAME_ASSETS_SOURCE="local"):
                    comp = items.extend(req, bundle, state=state)
                    out = items.extend(tpl, bundle, state=state)
                local_bases = {
                    "icons": "http://127.0.0.1:8015/icons",
                    "portraits": "http://127.0.0.1:8015/portraits",
                    "orchestrion": "http://127.0.0.1:8015/orchestrion",
                    "models": "http://127.0.0.1:8015/models",
                }
                self.assertEqual(json.loads(comp["data_files"][".data/runtime-assets.json"]), local_bases)
                self.assertEqual(out["data"]["assets"], local_bases)

                # 3. Remote TOS mode: all 4 kinds from TOS, with per-kind override supported
                tos = "https://tos.example/icexiv-db"
                state = {}
                with patch.dict(os.environ, GAME_ASSETS_SOURCE=tos):
                    comp = items.extend(req, bundle, state=state)
                    out = items.extend(tpl, bundle, state=state)
                remote_bases = {
                    "icons": f"{tos}/icons",
                    "portraits": f"{tos}/portraits",
                    "orchestrion": f"{tos}/orchestrion",
                    "models": f"{tos}/models",
                }
                self.assertEqual(json.loads(comp["data_files"][".data/runtime-assets.json"]), remote_bases)
                self.assertEqual(out["data"]["assets"], remote_bases)

    def test_install_sdk_verifies_digest_and_extracts_runtime_files_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "sdk.tgz"
            with tarfile.open(archive, "w:gz") as tar:
                for name in (*SDK_FILES, *EFFECT_SDK, "effects/icexiv_effects.d.ts"):
                    payload = f"content:{name}".encode()
                    info = tarfile.TarInfo("package/pkg/" + name)
                    info.size = len(payload)
                    tar.addfile(info, io.BytesIO(payload))
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            dest = root / "model-sdk"
            install_sdk(archive, digest, dest)
            for name in (*SDK_FILES, *EFFECT_SDK):
                self.assertEqual((dest / name).read_bytes(), f"content:{name}".encode())
            self.assertFalse((dest / "effects/icexiv_effects.d.ts").exists())
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                install_sdk(archive, "0" * 64, dest)
