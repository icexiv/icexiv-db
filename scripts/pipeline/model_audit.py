"""Audit the DB export against the 2026-11-03 CHS client; no model bytes are written.

cargo build -j4 --locked --release --manifest-path tools/game-export/Cargo.toml --example model_probe
python3 scripts/pipeline/model_audit.py ~/Games/ffxiv audit/model-audit.json
"""
from collections import Counter, defaultdict
from functools import cache
from pathlib import Path
import hashlib
import json
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SLOTS = {3: "met", 4: "top", 5: "glv", 7: "dwn", 8: "sho", 9: "ear",
         10: "nek", 11: "wrs", 12: "rir", 15: "top", 16: "top", 18: "dwn",
         19: "top", 20: "top", 21: "top", 22: "top", 23: "top"}
CHARA = {1322: "mount", 853: "companion", 20086: "ornament"}
# Concrete appearances of Minion of Light and the three Grand Company leaders.
COMPANION_FORMS = {67: (68, 69, 70), 71: (72, 73, 74)}


def audit(game, output):
    version_file = game / "game/ffxivgame.ver"
    version = version_file.read_text().strip()
    if version != "2026.11.03.0000.0000":
        raise ValueError("Review EXD column mapping for this client version")
    export = ROOT / "inputs/game-export"
    raw = (export / "items.json").read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    manifest = json.loads((export / "manifest.json").read_bytes())
    assert manifest["itemsSha256"] == digest
    items = json.loads(raw)
    resources = {}
    proc = subprocess.Popen([ROOT / "tools/game-export/target/release/examples/model_probe",
                             game / "game/sqpack"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)

    @cache
    def request(command):
        print(command, file=proc.stdin, flush=True)
        return json.loads(proc.stdout.readline())

    def sheet(command):
        rows = request("sheet " + command)
        result = {i: fields for i, *fields in rows}
        assert len(rows) == len(result)
        return result

    def model(row, path):
        result = request(path)
        if result is None:
            return False
        if "error" in result:
            row.setdefault("issues", {})[path] = result["error"]
            return False
        resources[path] = result["bytes"]
        if path not in row.setdefault("models", []):
            row["models"].append(path)
        return True

    def scene(row, root):
        pending, visited = [root], set()
        while pending:
            path = pending.pop()
            if path in visited:
                continue
            visited.add(path)
            result = request(path)
            if not result or "error" in result:
                row.setdefault("issues", {})[path] = (result or {}).get("error", "missing scene")
                continue
            for ref in result["refs"]:
                if ref.endswith(".sgb"):
                    pending.append(ref)
                elif ref.endswith(".mdl") and not model(row, ref):
                    row.setdefault("issues", {}).setdefault(ref, "missing scene model")

    result = {}
    with proc:
        current = sheet("item 10 14 17 30 47 48")
        actions = sheet("itemaction 4 5")
        links = {kind: sheet(f"{kind} {0 if kind == 'ornament' else 8}") for kind in CHARA.values()}
        charas = sheet("modelchara 0 1 2 3")
        bardings = sheet("buddyequip 9 10 11")
        glasses = sheet("glasses 0 1")
        furniture = defaultdict(list)
        for kind, table, col, prefix in [("indoor", "housingfurniture", 7, "fun"),
                                         ("outdoor", "housingyardobject", 6, "gar")]:
            for key, item_id in sheet(f"{table} 0 {col}").values():
                if item_id and key:
                    furniture[item_id].append((kind, f"bgcommon/hou/{kind}/general/{key:04}/asset/{prefix}_b0_m{key:04}.sgb"))
        for item in items:
            i = item["id"]
            row = result[i] = {"name": item["name"], "kind": "other", "status": "noMappedRoute"}
            fields = current.get(i)
            if not fields or fields[0] != item["icon"]:
                row["status"] = "sourceMismatch"
                continue
            _, additional, slot, action, main, sub = fields
            typ, target = actions[action]
            if typ in CHARA:
                kind = row["kind"] = CHARA[typ]
                ref, = links[kind].get(target, [0])
                row.update(target=target, modelChara=ref)
                forms = COMPANION_FORMS.get(target) if kind == "companion" and not ref else None
                for form in forms or (target,):
                    form_ref, = links[kind].get(form, [0])
                    if not form_ref or form_ref not in charas:
                        continue
                    t, m, b, v = charas[form_ref]
                    row.setdefault("appearance", charas[form_ref])
                    if t == 3:
                        path = f"chara/monster/m{m:04}/obj/body/b{b:04}/model/m{m:04}b{b:04}.mdl"
                        model(row, path)
                        if forms:
                            row.setdefault("modelVariants", {})[path] = v
                            row.setdefault("forms", []).append(dict(companion=form, modelChara=form_ref, model=path))
                    elif t == 2:
                        for part in ("met", "top", "glv", "dwn", "sho"):
                            model(row, f"chara/demihuman/d{m:04}/obj/equipment/e{b:04}/model/d{m:04}e{b:04}_{part}.mdl")
                    else:
                        row["issues"] = {"modelChara": f"unsupported type {t}"}
            elif i in furniture:
                row["kind"] = furniture[i][0][0]
                row["scenes"] = [p for _, p in furniture[i]]
                for p in row["scenes"]:
                    scene(row, p)
            elif typ == 1013:
                row.update(kind="barding", target=target)
                row["parts"] = bardings.get(target)
                for part, packed in zip(("met", "top", "sho"), row["parts"] or []):
                    if packed:
                        e = f"e{packed & 65535:04}"
                        if not model(row, f"chara/demihuman/d0001/obj/equipment/{e}/model/d0001{e}_{part}.mdl"):
                            row.setdefault("issues", {})[part] = "declared part not resolved"
            elif typ == 37312:
                # Shared ItemAction. AdditionalData selects Glasses, not Data[0].
                row.update(kind="facewear", glasses=additional)
                if additional in glasses:
                    packed, row["style"] = glasses[additional]
                    row["appearance"] = packed
                    e = f"e{packed & 65535:04}"
                    for race in range(101, 1802, 100):
                        if packed and model(row, f"chara/equipment/{e}/model/c{race:04}{e}_met.mdl"):
                            break
            elif slot in (1, 2, 13, 14):
                row.update(kind="weapon", main=main, sub=sub)
                for label, packed in (("main", main), ("sub", sub)):
                    if not packed:
                        continue
                    m, b, v = (packed >> n & 65535 for n in (0, 16, 32))
                    p = f"chara/weapon/w{m:04}/obj/body/b{b:04}/model/w{m:04}b{b:04}.mdl"
                    if not model(row, p) and not (m >= 8000 and b and not v and model(row,
                            f"chara/equipment/e{m:04}/model/c0101e{m:04}_glv.mdl")):
                        row.setdefault("issues", {})[label] = "declared part not resolved"
            elif slot in SLOTS:
                accessory = slot in (9, 10, 11, 12)
                row.update(kind="accessory" if accessory else "armor", main=main, slot=slot)
                m = main & 65535
                if m:
                    key = ("a" if accessory else "e") + f"{m:04}"
                    folder = "accessory" if accessory else "equipment"
                    for race in range(101, 1802, 100):
                        if model(row, f"chara/{folder}/{key}/model/c{race:04}{key}_{SLOTS[slot]}.mdl"):
                            break
            elif main & 65535 == 9901 and not slot:
                row.update(kind="heldProp", main=main)
                b = f"b{(main >> 16) & 65535:04}"
                model(row, f"chara/weapon/w9901/obj/body/{b}/model/w9901{b}.mdl")
            elif main or sub:
                row.update(kind="unroutedModelFields", main=main, sub=sub, slot=slot)
            if row["kind"] != "other":
                if row.get("models"):
                    row["status"] = "geometryLocated"
                elif any(p.endswith(".mdl") and "unsupported MDL version" in msg
                         for p, msg in row.get("issues", {}).items()):
                    row["status"] = "unsupportedMdl"
                else:
                    row["status"] = "unresolved"
        proc.stdin.close()
        if proc.wait():
            raise RuntimeError("SqPack probe failed")
    assert len(result) == len(items) == manifest["itemCount"] and version_file.read_text().strip() == version
    counts = defaultdict(Counter)
    for row in result.values():
        counts[row["kind"]][row["status"]] += 1
    summary = dict(items=len(result), byKind=counts, uniqueModels=len(resources),
                   uniqueModelBytes=sum(resources.values()))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(dict(itemVersion=manifest["source"]["gameVersion"], resourceVersion=version,
                                      itemsSha256=digest, summary=summary, items=result, models=resources),
                                 ensure_ascii=False, separators=(",", ":")) + "\n")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    audit(*map(Path, sys.argv[1:]))
