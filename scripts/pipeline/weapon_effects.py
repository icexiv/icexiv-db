"""Attach actual IMC-mounted VFX to every matching preview MDL.

Weapons, equipment, accessories, facewear, barding, mounts, minions and
ornaments all use the same IMC -> AVFX -> bind-point contract. The renderer
exporter resolves the owner-specific paths; this stage only maps each item's
audit row onto its manifest parts and stores the resulting closure.
"""
from collections import Counter
from functools import cache
import json
import hashlib
import re
import struct
from pathlib import Path
import subprocess

if __package__:
    from .model_library import write
else:
    from model_library import write

ROOT = Path(__file__).resolve().parents[2]
EXPORTER = ROOT.parent / "icexiv-renderer/effects/target/release/examples/export"
SLOT_CATEGORY = {"met": 3, "top": 4, "glv": 5, "dwn": 7, "sho": 8,
                 "ear": 9, "nek": 10, "wrs": 11, "rir": 12, "ril": 12}
BARDING_SLOTS = ("met", "top", "sho")
SUPPORTED_KINDS = {"weapon", "heldProp", "armor", "accessory", "facewear",
                   "barding", "mount", "companion", "ornament"}


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


def model_suffix(model):
    return model.rsplit("_", 1)[-1].rsplit(".", 1)[0]


def race_of(model):
    match = re.search(r"/model/c(\d{4})", model)
    return int(match.group(1)) if match else 101


def slot_category(model):
    return SLOT_CATEGORY.get(model_suffix(model))


def set_id_of(model):
    match = re.search(r"/[ea](\d{4})/model/", model)
    return int(match.group(1)) if match else 0


def chara_ids(model):
    """ModelChara-style ids from an actual monster/demihuman model path."""
    match = re.search(r"/monster/m(\d{4})/obj/body/b(\d{4})/", model)
    if match:
        return int(match.group(1)), int(match.group(2)), False
    match = re.search(r"/demihuman/d(\d{4})/obj/equipment/e(\d{4})/", model)
    if match:
        return int(match.group(1)), int(match.group(2)), True
    return None


def item_specs(item, parts):
    """Yield exporter descriptors for the parts that could own an effect."""
    kind = item.get("kind")
    if kind in ("weapon", "heldProp"):
        for raw in dict.fromkeys(raw for raw in (item.get("main"), item.get("sub")) if raw):
            yield {"kind": "weapon", "main": raw}
        return
    if kind in ("armor", "accessory", "facewear"):
        main = item.get("main") if kind != "facewear" else item.get("appearance")
        if not main:
            return
        for part in parts:
            model = part.get("model", "")
            slot = item.get("slot") if kind != "facewear" else slot_category(model)
            if kind != "facewear" and item.get("main", 0) & 65535 != set_id_of(model):
                continue
            if not slot:
                continue
            yield {"kind": "equipment", "main": main, "slot": slot,
                   "race": race_of(model), "model_path": model}
        return
    if kind == "barding":
        packed_by_slot = dict(zip(BARDING_SLOTS, item.get("parts") or []))
        for part in parts:
            model = part.get("model", "")
            packed = packed_by_slot.get(model_suffix(model))
            if not packed:
                continue
            ids = chara_ids(model) or (1, set_id_of(model), True)
            yield {"kind": "chara", "model": ids[0], "base": ids[1],
                   "variant": (packed >> 16) & 0xFFFF, "demihuman": True,
                   "chara_kind": "mount", "model_path": model}
        return
    if kind in ("mount", "companion", "ornament"):
        appearance = item.get("appearance") or []
        if len(appearance) < 4:
            return
        chara_type, model_id, base_id, variant_id = appearance[:4]
        variants = item.get("modelVariants") or {}
        for part in parts:
            model = part.get("model", "")
            ids = chara_ids(model)
            if ids:
                model_id, base_id, demihuman = ids
            else:
                demihuman = chara_type == 2
            yield {"kind": "chara", "model": model_id, "base": base_id,
                   "variant": int(variants.get(model, variant_id) or 1),
                   "demihuman": demihuman, "chara_kind": kind,
                   "model_path": model}


def attach(game, audit_path, library, report_path, only=None):
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
            if only is not None and i not in only:
                continue
            kind = item.get("kind")
            if kind not in SUPPORTED_KINDS:
                counts[f"unsupported:{kind}"] += 1
                continue
            path = library / "manifests" / f"{i}.json"
            if not path.exists():
                counts["noStaticPreview"] += 1
                continue
            manifest = json.loads(path.read_bytes())
            parts = manifest["parts"]
            by_model = {part["model"]: part for part in parts}
            attached = False
            for spec in item_specs(item, parts):
                desc = inspect(json.dumps(spec, ensure_ascii=False, separators=(",", ":")))
                if desc is None:
                    continue
                if "error" in desc:
                    issues.setdefault(i, []).append(desc["error"])
                    continue
                owner = desc.get("owner")
                part = by_model.get(owner)
                if part is None:
                    issues.setdefault(i, []).append(
                        f"VFX owner differs from preview geometry: {owner}")
                    continue
                part["effect"] = desc
                attached = True
                if desc.get("diagnostics"):
                    issues.setdefault(i, []).extend(desc["diagnostics"])
            if attached:
                write(path, manifest)
                counts["attachedWithDiagnostics" if i in issues else "attached"] += 1
            else:
                counts["unresolved" if i in issues else "noMount"] += 1
        probe.stdin.close()
        if probe.wait():
            raise RuntimeError("VFX extraction failed")
    write(report_path, dict(resourceVersion=audit["resourceVersion"],
                            itemCount=sum(v for k, v in counts.items() if not k.startswith("unsupported:")),
                            counts=counts, issues=issues))
    print("Item effects:", dict(counts), flush=True)
