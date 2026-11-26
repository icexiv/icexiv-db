"""Attach actual IMC mounts to the matching preview MDL. Keep VFX coverage separate."""
from collections import Counter
from functools import cache
import json
import hashlib
import struct
from pathlib import Path
import subprocess

if __package__:
    from .model_library import write
else:
    from model_library import write

ROOT = Path(__file__).resolve().parents[2]
EXPORTER = ROOT.parent / "icexiv-renderer/effects/target/release/examples/export"


def material_package(data):
    """WebGPU uses its own shaders; retain the DX11 material tables and names."""
    # Only rewrite the known little-endian ShPk layout. Future layouts pass through.
    if len(data) < 88 or data[:12] != b"ShPk\x01\x0e\0\0DX11":
        return data
    length, programs, strings, vertices, pixels, defaults = struct.unpack_from("<6I", data, 12)
    if not (88 <= programs <= strings <= length == len(data)):
        return data
    hull, domain, geo = struct.unpack_from("<3I", data, 72)
    pos = 88
    for _ in range(vertices + pixels + hull + domain + geo):
        if pos + 20 > programs:
            return data
        pos += 20 + 16 * sum(struct.unpack_from("<4H", data, pos + 8))
    params, has_defaults, scalar, sampler, texture, uav, system, scene, material = struct.unpack_from("<HHIHH4I", data, 36)
    end = pos + params*8 + (defaults if has_defaults else 0) + 16*(scalar+sampler+texture+uav) + 8*(system+scene+material+1)
    if end > programs:
        return data
    header = bytearray(data[:88])
    offset = 88 + end - pos
    struct.pack_into("<5I", header, 12, offset + length - strings, offset, offset, 0, 0)
    header[64:88] = bytes(24)  # nodes, aliases, optional shader stages and alias clusters
    return bytes(header) + data[pos:end] + data[strings:]


def compact_packages(objects):
    @cache
    def compact(sha):
        original = (objects / sha[:2] / sha[2:]).read_bytes()
        data = material_package(original)
        if data == original:
            return sha
        digest = hashlib.sha256(data).hexdigest()
        path = objects / digest[:2] / digest[2:]
        path.parent.mkdir(exist_ok=True)
        if not path.exists():
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(data)
            tmp.replace(path)
        return digest
    return compact


def attach(game, audit_path, library, report_path):
    audit = json.loads(audit_path.read_bytes())
    if (game / "game/ffxivgame.ver").read_text().strip() != audit["resourceVersion"]:
        raise ValueError("VFX audit and client versions differ")
    cache_dir = library / "objects/sha256"
    counts, issues = Counter(), {}
    compact = compact_packages(cache_dir)
    with subprocess.Popen([EXPORTER, game / "game", cache_dir], stdin=subprocess.PIPE,
                          stdout=subprocess.PIPE, text=True) as probe:
        @cache
        def inspect(raw):
            print(raw, file=probe.stdin, flush=True)
            desc = json.loads(probe.stdout.readline())
            for path, sha in (desc or {}).get("files", {}).items():
                if path.endswith(".shpk"):
                    desc["files"][path] = compact(sha)
            return desc

        for i, item in audit["items"].items():
            if item["kind"] != "weapon":
                continue
            path = library / "manifests" / f"{i}.json"
            if not path.exists():
                counts["noStaticPreview"] += 1
                continue
            manifest = json.loads(path.read_bytes())
            parts = {p["model"]: p for p in manifest["parts"]}
            attached = False
            for raw in dict.fromkeys([item["main"], item["sub"]]):
                if not raw:
                    continue
                desc = inspect(raw)
                if desc is None:
                    continue
                if "error" in desc or desc["owner"] not in parts:
                    issues.setdefault(i, []).append(desc.get("error", "VFX owner differs from preview geometry"))
                    continue
                parts[desc["owner"]]["effect"] = desc
                attached = True
                if desc["diagnostics"]:
                    issues.setdefault(i, []).extend(desc["diagnostics"])
            if attached:
                write(path, manifest)
            counts["attachedWithDiagnostics" if attached and i in issues else
                   "attached" if attached else "unresolved" if i in issues else "noMount"] += 1
        probe.stdin.close()
        if probe.wait():
            raise RuntimeError("VFX extraction failed")
    write(report_path, dict(resourceVersion=audit["resourceVersion"], weaponItems=sum(counts.values()),
                            counts=counts, issues=issues))
    print("Weapon effects:", dict(counts), flush=True)
