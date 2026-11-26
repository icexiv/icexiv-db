"""Prepare local on-demand viewer manifests from a complete model_audit.py run."""
from collections import Counter, defaultdict
from functools import cache
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
PARTS = dict(met=0, ear=0, top=1, nek=1, glv=2, wrs=2, dwn=3, rir=3, sho=4, ril=4)
ANIMATION_RECORD = "cbnm_id0"
ANIMATED_KINDS = {"armor", "accessory", "facewear"}


def animation_paths(kind, models):
    """Shared base skeleton and idle PAP for human gear, by the model's clade."""
    if kind not in ANIMATED_KINDS:
        return None
    for model in models:
        match = re.search(r"chara/(?:equipment|accessory)/[^/]+/model/(c\d{4})", model)
        if match:
            clade = match.group(1)
            return (f"chara/human/{clade}/skeleton/base/b0001/skl_{clade}b0001.sklb",
                    f"chara/human/{clade}/animation/a0001/bt_common/resident/idle.pap")
    return None


def write(path, value):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, separators=(",", ":"), ensure_ascii=False))
    tmp.replace(path)


def variants(row, mdl):
    kind = row["kind"]
    if kind in ("indoor", "outdoor"):
        return 1
    if kind in ("armor", "accessory"):
        return row["main"] >> 16 & 65535
    if kind == "facewear":
        return row["appearance"] >> 16 & 65535
    if kind == "barding":
        slot = mdl[-7:-4]
        return row["parts"][("met", "top", "sho").index(slot)] >> 16 & 65535
    if kind in ("mount", "companion", "ornament"):
        return row.get("modelVariants", {}).get(mdl, row["appearance"][3])
    for raw in (row.get("main", 0), row.get("sub", 0)):
        if f"chara/equipment/e{raw & 65535:04}/" in mdl:
            return raw >> 16 & 65535
        if f"w{raw & 65535:04}/obj/body/b{raw >> 16 & 65535:04}" in mdl:
            return raw >> 32 & 65535
    return None


def build(game, sdk, output, audit_path=ROOT / "audit/model-audit.json"):
    audit = json.loads(audit_path.read_text())
    version = (game / "game/ffxivgame.ver").read_text().strip()
    if audit["resourceVersion"] != version:
        raise ValueError("audit/client version mismatch")
    manifests = output / "manifests"
    manifests.mkdir(parents=True, exist_ok=True)
    # Only publish the inventory after both object extraction and manifest generation succeed.
    inventory = output / "inventory.json"
    inventory.unlink(missing_ok=True)
    sdk_dir = output / "sdk"
    sdk_dir.mkdir(exist_ok=True)
    for file in ("icexiv_renderer.js", "icexiv_renderer_bg.wasm", "component.js"):
        shutil.copyfile(sdk / file, sdk_dir / file)
    counts, reasons, by_kind = Counter(), Counter(), defaultdict(Counter)
    items, failures, invisible = {}, {}, {}
    proc = subprocess.Popen([ROOT / "target/renderer-probe/release/icexiv-db-renderer-probe",
                             game / "game/sqpack", output / "objects/sha256"],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)

    @cache
    def probe(path):
        if "\n" in path or "\r" in path:
            raise ValueError("invalid resource name")
        print(path, file=proc.stdin, flush=True)
        return json.loads(proc.stdout.readline())

    @cache
    def material_version(mdl, subset):
        if subset is None or mdl.startswith("bgcommon/"):
            return subset, None
        root = mdl.rsplit("/", 2)[0]
        path = f"{root}/{root.split('/')[-1]}.imc"
        imc = probe(path)
        if imc is None:
            return subset or 1, None
        if "error" in imc:
            return None, ["IMC decode", path, imc["error"], mdl]
        rows = imc.get("subsets", [])
        if subset >= len(rows):
            return None, ["IMC subset not resolved", path, f"subset {subset}", mdl]
        parts = rows[subset]
        part = PARTS.get(mdl[-7:-4], 0)
        version = parts.get(str(part)) if len(parts) != 1 else next(iter(parts.values()))
        return version, None if version is not None else ["IMC part not resolved", path, f"part {part}", mdl]

    @cache
    def material_paths(name, mdl, version):
        return probe("paths " + json.dumps([mdl, name, version]))

    @cache
    def slot(name, mdl, version):
        paths = list(material_paths(name, mdl, version))
        for path in paths:
            m = probe(path)
            if m is None:
                continue
            if "error" in m:
                return None, "material: " + m["error"], path
            tex = m["texture"]
            t = probe(tex) if tex else {"sha": "-"}
            if not t or "error" in t:
                return None, "texture not resolved", tex
            diffuse = m.get("diffuse")
            d = probe(diffuse) if diffuse else {"sha": "-"}
            if not d or "error" in d:
                return None, "texture not resolved", diffuse
            result = probe(f"pair {m['sha']} {t['sha']} {d['sha']}")
            if "error" in result:
                return None, "texture decode: " + result["error"], tex
            textures = {k: v for k, v in ((tex, t["sha"]), (diffuse, d["sha"])) if k}
            return (path, m["sha"], textures), None, None
        return None, "material path not resolved", paths[0]

    with proc:
        for i, row in audit["items"].items():
            if not row.get("models"):
                continue
            parts, files, gaps, empty_models = [], {}, [], []
            colored = total = 0
            for mdl in row["models"]:
                geom = probe(mdl)
                if not geom or "error" in geom:
                    gaps.append(["geometry", mdl, (geom or {}).get("error", "not found")])
                    continue
                if geom.get("noVisibleExtent"):
                    empty_models.append(mdl)
                    continue
                files[mdl] = geom["sha"]
                mats = {}
                fallbacks = []
                ver, issue = material_version(mdl, variants(row, mdl))
                if issue:
                    gaps.append(issue)
                for name in geom["slots"]:
                    total += 1
                    found, error, path = slot(name, mdl, ver)
                    requested = material_paths(name, mdl, ver)[0]
                    strategy = "materialDirectory"
                    # Mirrored weapon pairs may ship only the main-hand material.
                    # Restrict substitution to the same item, body and slot suffix.
                    if error == "material path not resolved" and parts and row["kind"] == "weapon":
                        main, sub = row["main"], row["sub"]
                        w, b = main & 65535, main >> 16 & 65535
                        match = re.fullmatch(r"/mt_w\d{4}b(\d{4})(_\w+\.mtrl)", name)
                        sub_id = sub & 65535
                        if (match and sub_id == w + 50 and int(match[1]) == b == (sub >> 16 & 65535)
                                and f"/w{sub_id:04}/obj/body/b{b:04}/" in mdl
                                and f"/w{w:04}/obj/body/b{b:04}/" in parts[0]["model"]):
                            paired = f"/mt_w{w:04}b{b:04}{match[2]}"
                            if paired in parts[0]["materials"]:
                                main_mdl = parts[0]["model"]
                                main_ver, _ = material_version(main_mdl, variants(row, main_mdl))
                                found, error, path = slot(paired, main_mdl, main_ver)
                                strategy = "pairedMainHand"
                    if error:
                        gaps.append([error, path, name, mdl])
                        continue
                    mat, mh, textures = found
                    files[mat] = mh
                    files.update(textures)
                    mats[name] = mat
                    if mat != requested:
                        fallbacks.append(dict(slot=name, requested=requested, resolved=mat, strategy=strategy))
                    colored += 1
                parts.append(dict(model=mdl, materials=mats, slots=len(geom["slots"]), triangles=geom["triangles"]))
                if fallbacks:
                    parts[-1]["materialFallbacks"] = fallbacks
            if empty_models:
                invisible[i] = empty_models
            state = ("noVisibleSurface" if not parts and not gaps and empty_models else
                     "rejected" if not parts else "neutral" if not colored else
                     "allSlots" if total == colored else "partial")
            counts[state] += 1
            by_kind[row["kind"]][state] += 1
            reasons.update(set(g[0] for g in gaps))
            if gaps:
                failures[i] = gaps
            if not parts:
                continue
            if len(parts) > 1:
                counts["multiPart"] += 1
            manifest = dict(parts=parts, files=files, sdk="../sdk/icexiv_renderer.js",
                            objects="../objects/sha256/", version=version, kind=row["kind"], gaps=gaps,
                            incompleteParts=bool(row.get("issues") or len(parts) != len(row["models"])))
            if anim := animation_paths(row["kind"], [p["model"] for p in parts]):
                animation = dict(zip(("sklb", "pap"), anim), record=ANIMATION_RECORD)
                resolved = {path: probe(path) for path in anim}
                if all(r and "sha" in r for r in resolved.values()):
                    files.update({path: resolved[path]["sha"] for path in anim})
                    manifest["animation"] = animation
            if parts[0]["triangles"] == 1:
                manifest["defaultPart"] = max(range(len(parts)), key=lambda j: parts[j]["triangles"])
            if row.get("forms"):
                manifest["alternativeForms"] = True
            write(manifests / f"{i}.json", manifest)
            items[i] = state
        proc.stdin.close()
        if proc.wait():
            raise RuntimeError("resource probe failed")
    if version != (game / "game/ffxivgame.ver").read_text().strip():
        raise RuntimeError("client changed during extraction")
    write(output / "gaps.json", failures)
    write(output / "no-visible-surface.json", invisible)
    report = dict(version=version, sdkWasmSha256=hashlib.sha256(
        (sdk_dir / "icexiv_renderer_bg.wasm").read_bytes()).hexdigest(),
        itemsSha256=audit["itemsSha256"], counts=counts, byKind=by_kind, reasons=reasons)
    write(output / "report.json", report)
    write(inventory, dict(itemsSha256=audit["itemsSha256"], items=items))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    build(*map(Path, sys.argv[1:]))
