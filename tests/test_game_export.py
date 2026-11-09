"""Synthetic EXH/EXD/SqPack fixtures authored for the game export command."""
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
import zlib

VERSION = "2026.10.06.0000.0000"


def put32(data, offset, value):
    struct.pack_into("<I", data, offset, value)


def container(kind):
    data = bytearray(0x800)
    data[:8] = b"SqPack\0\0"
    for offset, value in [(12, 0x400), (16, 1), (20, kind), (0x400, 0x400)]:
        put32(data, offset, value)
    return data


def texture(valid=True):
    tex = bytearray(84)
    put32(tex, 0, 0x00800000)
    put32(tex, 4, 0x1450 if valid else 0xffffffff)
    for pos in [8, 10, 12]:
        struct.pack_into("<H", tex, pos, 1)
    tex[14] = 1
    put32(tex, 28, 80)
    tex[80:] = bytes([10, 20, 30, 40])
    return tex


def synthetic_pack(root, resources):
    directory = root / "game/sqpack/ffxiv"
    directory.mkdir(parents=True)
    for category, number in [("ui", "06"), ("exd", "0a")]:
        dat = container(1)
        records = []
        for path, kind, payload in resources:
            if path.split("/")[0] != category:
                continue
            records.append(((~zlib.crc32(path.encode())) & 0xffffffff, len(dat) // 8))
            stored = payload[80:] if kind == 4 else payload
            span = (16 + len(stored) + 127) // 128 * 128
            prefix = payload[:80] if kind == 4 else b""
            size = (128 + len(prefix) + span + 127) // 128 * 128
            entry = bytearray(size)
            for pos, value in [(0, 128), (4, kind), (8, len(payload)), (20, 1)]:
                put32(entry, pos, value)
            if kind == 4:
                for pos, value in [(24, 80), (28, span), (32, len(stored)), (40, 1)]:
                    put32(entry, pos, value)
                struct.pack_into("<H", entry, 44, span)
            else:
                struct.pack_into("<IHH", entry, 24, 0, span, len(stored))
            entry[128:128 + len(prefix)] = prefix
            block = 128 + len(prefix)
            for pos, value in [(block, 16), (block + 8, 32000), (block + 12, len(stored))]:
                put32(entry, pos, value)
            entry[block + 16:block + 16 + len(stored)] = stored
            dat.extend(entry)
        index = container(2)
        for pos, value in [(0x404, 1), (0x408, 0x800), (0x40c, len(records) * 8)]:
            put32(index, pos, value)
        for hash_value, location in sorted(records):
            index.extend(struct.pack("<II", hash_value, location))
        (directory / f"{number}0000.win32.index2").write_bytes(index)
        (directory / f"{number}0000.win32.dat0").write_bytes(dat)


def sheet_fixture(root, bad_hr=False):
    names = ["name", "description", "icon", "category", "searchCategory", "equipLevel", "rarity", "stackSize", "unique", "untradable", "hq"]
    kinds = [0, 0, 5, 3, 3, 3, 3, 7, 0x19, 0x1a, 0x1d]
    labels = ["String", "String", "UInt16", "UInt8", "UInt8", "UInt8", "UInt8", "UInt32", "PackedBool(0)", "PackedBool(1)", "PackedBool(4)"]
    offsets = [0, 4, 8, 10, 11, 12, 13, 14, 18, 18, 18]
    header = bytearray(32)
    header[:4] = b"EXHF"
    struct.pack_into(">HHHHH", header, 4, 3, 19, 11, 1, 1)
    header[17] = 1
    struct.pack_into(">I", header, 20, 6)
    for kind, offset in zip(kinds, offsets):
        header.extend(struct.pack(">HH", kind, offset))
    header.extend(struct.pack(">II", 0, 6))
    header.extend(struct.pack("<H", 5))
    page = bytearray(32 + 6 * 8)
    page[:4] = b"EXDF"
    struct.pack_into(">H", page, 4, 2)
    struct.pack_into(">I", page, 8, 6 * 8)
    for row_id, (name, icon) in enumerate([(b"", 0), ("甲".encode(), 12), (b"Beta", 12), (b"Gamma", 13), (b"Delta", 0), (b" ", 0)]):
        description = b"one\x02\x10\x01\x03two"
        fixed = bytearray(19)
        struct.pack_into(">IIHBBBBI", fixed, 0, 0, len(name) + 1, icon, 3, 4, 5, 1, 99)
        fixed[18] = 0x13
        payload = fixed + name + b"\0" + description + b"\0"
        struct.pack_into(">II", page, 32 + row_id * 8, row_id, len(page))
        page.extend(struct.pack(">IH", len(payload), 1) + payload)
    struct.pack_into(">I", page, 12, len(page) - 32 - 6 * 8)
    schema = {"version": 1, "gameVersion": VERSION, "language": "chs",
              "exhSha256": hashlib.sha256(header).hexdigest(),
              "fields": {name: {"column": column, "kind": label} for column, (name, label) in enumerate(zip(names, labels))}}
    resources = [("exd/item.exh", 2, header), ("exd/item_0_chs.exd", 2, page),
                 ("ui/icon/000000/000012.tex", 4, texture())]
    if bad_hr:
        resources.append(("ui/icon/000000/000012_hr1.tex", 4, texture(False)))
    synthetic_pack(root, resources)
    (root / "game/ffxivgame.ver").write_text(VERSION)
    (root / "schema.json").write_text(json.dumps(schema))
    return schema


@unittest.skipUnless(os.environ.get("GAME_EXPORT_TEST_BIN"), "Set GAME_EXPORT_TEST_BIN to test the game export command")
class GameExportTests(unittest.TestCase):
    def run_export(self, root):
        return subprocess.run([os.environ["GAME_EXPORT_TEST_BIN"], str(root / "schema.json"), str(root), str(root / "output")],
                              capture_output=True, text=True)

    def test_sheet_fields_text_icons_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sheet_fixture(root)
            result = self.run_export(root)
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads((root / "output/manifest.json").read_text())
            records = json.loads((root / "output/items.json").read_text())
            self.assertEqual([item["id"] for item in records], [1, 2, 3, 4])
            self.assertEqual(records[0]["name"], "甲")
            self.assertEqual(records[0]["description"], "one\ntwo")
            self.assertEqual(records[0]["stackSize"], 99)
            self.assertTrue(all(records[0][key] for key in ["unique", "untradable", "hq"]))
            self.assertEqual(manifest["icons"]["0"]["status"], "unconfigured")
            self.assertEqual(manifest["icons"]["13"]["status"], "missing")
            self.assertEqual(manifest["icons"]["12"]["resource"], "ui/icon/000000/000012.tex")
            png = root / "output/icons/12.png"
            original = png.read_bytes()
            self.assertEqual(original[:8], b"\x89PNG\r\n\x1a\n")
            self.assertNotEqual(self.run_export(root).returncode, 0)
            self.assertEqual(png.read_bytes(), original)

    def test_decode_failure_does_not_fall_back(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sheet_fixture(root, bad_hr=True)
            self.assertNotEqual(self.run_export(root).returncode, 0)
            manifest = json.loads((root / "output/manifest.json").read_text())
            self.assertEqual(manifest["icons"]["12"]["status"], "failed")
            self.assertFalse((root / "output/icons/12.png").exists())

    def test_wrong_version_header_and_field_type_are_rejected_before_output(self):
        for mutation in ["version", "hash", "type"]:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                schema = sheet_fixture(root)
                if mutation == "version":
                    (root / "game/ffxivgame.ver").write_text("2000.01.01.0000.0000")
                elif mutation == "hash":
                    schema["exhSha256"] = "0" * 64
                else:
                    schema["fields"]["icon"]["kind"] = "String"
                (root / "schema.json").write_text(json.dumps(schema))
                self.assertNotEqual(self.run_export(root).returncode, 0)
                self.assertFalse((root / "output").exists())
