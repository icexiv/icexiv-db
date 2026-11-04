"""Synthetic SqPack fixtures authored for the consumer export command."""
import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
import zlib


def put32(data, offset, value):
    struct.pack_into("<I", data, offset, value)


def container(kind):
    data = bytearray(0x800)
    data[:8] = b"SqPack\0\0"
    for offset, value in [(12, 0x400), (16, 1), (20, kind), (0x400, 0x400)]:
        put32(data, offset, value)
    return data


def synthetic_pack(root, resources):
    """One UI index2 and DAT with raw, one-level type-4 entries."""
    directory = root / "ffxiv"
    directory.mkdir(parents=True)
    dat = container(1)
    records = []
    for path, valid in resources:
        offset = len(dat)
        records.append(((~zlib.crc32(path.encode())) & 0xffffffff, offset // 8))
        entry = bytearray(256)
        for pos, value in [(0, 128), (4, 4), (8, 84), (20, 1), (24, 80),
                           (28, 32), (32, 4), (40, 1)]:
            put32(entry, pos, value)
        struct.pack_into("<H", entry, 44, 32)
        tex = bytearray(80)
        put32(tex, 0, 0x00800000)
        put32(tex, 4, 0x1450 if valid else 0xffffffff)
        for pos in [8, 10, 12]:
            struct.pack_into("<H", tex, pos, 1)
        tex[14] = 1
        put32(tex, 28, 80)
        entry[128:208] = tex
        for pos, value in [(208, 16), (216, 32000), (220, 4)]:
            put32(entry, pos, value)
        entry[224:228] = bytes([10, 20, 30, 40])
        dat.extend(entry)
    index = container(2)
    for pos, value in [(0x404, 1), (0x408, 0x800), (0x40c, len(records) * 8)]:
        put32(index, pos, value)
    for hash_value, location in sorted(records):
        index.extend(struct.pack("<II", hash_value, location))
    (directory / "060000.win32.index2").write_bytes(index)
    (directory / "060000.win32.dat0").write_bytes(dat)


@unittest.skipUnless(os.environ.get("ICON_EXPORT_TEST_BIN"), "Set ICON_EXPORT_TEST_BIN to test the export command")
class IconExportTests(unittest.TestCase):
    def run_export(self, root, version="synthetic"):
        return subprocess.run([os.environ["ICON_EXPORT_TEST_BIN"], str(root / "request.json"),
                               str(root / "sqpack"), version, str(root / "output")],
                              capture_output=True, text=True)

    def request(self, root):
        (root / "request.json").write_text(json.dumps({
            "version": 1, "gameVersion": "synthetic", "csvSha256": "a" * 64,
            "iconIds": [0, 12, 12, 13],
        }))

    def test_deduplication_fallback_missing_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.request(root)
            synthetic_pack(root / "sqpack", [("ui/icon/000000/000012.tex", True)])
            result = self.run_export(root)
            self.assertEqual(result.returncode, 0, result.stderr)
            export = json.loads((root / "output/manifest.json").read_text())
            self.assertEqual(len(export["icons"]), 3)
            self.assertEqual(export["icons"]["0"]["status"], "unconfigured")
            self.assertEqual(export["icons"]["13"]["status"], "missing")
            self.assertEqual(export["icons"]["12"]["resource"], "ui/icon/000000/000012.tex")
            png = root / "output/12.png"
            original = png.read_bytes()
            self.assertEqual(original[:8], b"\x89PNG\r\n\x1a\n")
            self.assertNotEqual(self.run_export(root).returncode, 0)
            self.assertEqual(png.read_bytes(), original)

    def test_decode_failure_does_not_fall_back_or_become_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.request(root)
            synthetic_pack(root / "sqpack", [("ui/icon/000000/000012_hr1.tex", False),
                                              ("ui/icon/000000/000012.tex", True)])
            result = self.run_export(root)
            self.assertNotEqual(result.returncode, 0)
            export = json.loads((root / "output/manifest.json").read_text())
            self.assertEqual(export["icons"]["12"]["status"], "failed")
            self.assertFalse((root / "output/12.png").exists())

    def test_version_mismatch_does_not_create_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.request(root)
            self.assertNotEqual(self.run_export(root, "different").returncode, 0)
            self.assertFalse((root / "output").exists())
