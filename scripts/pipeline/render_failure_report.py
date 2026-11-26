"""Join the full item-route audit and renderer probe without losing upstream failures.

Run after model_audit.py and model_library.py:
  python3 scripts/pipeline/render_failure_report.py audit/render-check
"""
from collections import Counter, defaultdict
import csv
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]


def read(path):
    return json.loads(path.read_bytes())


def csv_file(path, fields, rows):
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fields)
        writer.writeheader()
        writer.writerows(rows)


def build(directory):
    audit = read(directory / "model-audit.json")
    lib = directory / "library"
    inventory, gaps, report = (read(lib / name) for name in ("inventory.json", "gaps.json", "report.json"))
    raw = (ROOT / "inputs/game-export/items.json").read_bytes()
    ids = {str(item["id"]) for item in json.loads(raw)}
    items = audit["items"]
    ready = inventory["items"]
    assert hashlib.sha256(raw).hexdigest() == audit["itemsSha256"] == inventory["itemsSha256"] == report["itemsSha256"]
    assert audit["resourceVersion"] == report["version"] and ids == items.keys()
    attempted = {i for i, item in items.items() if item.get("models")}
    empty_path = lib / "no-visible-surface.json"
    empty = set(read(empty_path)) - ready.keys() - gaps.keys() if empty_path.exists() else set()
    assert ready.keys() <= attempted and gaps.keys() <= attempted
    assert len(empty) == report["counts"].get("noVisibleSurface", 0)
    assert len(attempted - ready.keys() - empty) == report["counts"].get("rejected", 0)
    assert Counter(ready.values()) == Counter({state: report["counts"].get(state, 0)
                                               for state in ("allSlots", "partial", "neutral")})
    assert attempted - ready.keys() - empty <= gaps.keys()

    details, item_rows = [], []
    reasons, paths = defaultdict(set), defaultdict(set)
    by_outcome = Counter()
    for i in sorted(ids, key=int):
        item = items[i]
        errors = []

        def add(stage, reason, ref="", detail="", owner=""):
            errors.append(dict(id=i, name=item["name"], kind=item["kind"], stage=stage,
                               reason=reason, resource=ref, detail=detail, owner=owner))
            reasons[reason].add(i)
            if ref:
                paths[(stage, reason, ref)].add(i)

        for ref, msg in item.get("issues", {}).items():
            if ref in ("main", "sub") and msg == "declared part not resolved":
                # Part-level consequence; retain which parts failed in the item row.
                # Only count it as the primary failure if there is no file-level diagnosis.
                if not any(p.endswith(".mdl") for p in item["issues"]):
                    add("modelLookup", msg, detail=ref)
            elif msg.startswith("unsupported MDL version"):
                add("mdlParse", msg, ref)
            else:
                add("modelLookup", msg, ref)
        if item["status"] == "unresolved" and not errors:
            if item.get("modelChara") == 0:
                add("targetLookup", "no direct ModelChara reference", detail=f"{item['kind']} row {item['target']}")
            else:
                add("targetLookup", "unresolved model reference")
        if item["status"] == "sourceMismatch":
            add("targetLookup", "source mismatch")
        for reason, path, detail, *owner in gaps.get(i, []):
            if reason == "geometry":
                stage, reason = "rendererGeometry", detail
            elif reason.startswith("IMC"):
                stage = "imc"
            elif reason.startswith("texture"):
                stage = "tex"
            else:
                stage = "mtrl"
            add(stage, reason, path, detail, owner[0] if owner else "")
        assert item["status"] != "unsupportedMdl" or errors
        if i in ready:
            outcome = "previewWithIssues" if errors else "previewWithoutReportedIssues"
        elif errors:
            outcome = "noPreviewWithIssues"
        elif i in empty:
            outcome = "noVisibleSurface"
        else:
            assert item["status"] == "noMappedRoute"
            outcome = "noMappedRoute"
        by_outcome[outcome] += 1
        details.extend(errors)
        item_rows.append(dict(id=i, name=item["name"], kind=item["kind"], outcome=outcome,
                              slotStatus=ready.get(i, ""), routeStatus=item["status"],
                              failedParts=";".join(k for k in ("main", "sub") if k in item.get("issues", {})),
                              reasons="; ".join(sorted({e["reason"] for e in errors}))))
    failed = [r for r in item_rows if r["reasons"]]
    assert {r["id"] for r in failed} == {r["id"] for r in details}
    assert len(failed) == by_outcome["previewWithIssues"] + by_outcome["noPreviewWithIssues"]
    assert sum(by_outcome.values()) == len(ids)
    csv_file(directory / "all-items.csv", item_rows[0].keys(), item_rows)
    csv_file(directory / "failed-items.csv", item_rows[0].keys(), failed)
    csv_file(directory / "failure-details.csv", ("id", "name", "kind", "stage", "reason", "resource", "detail", "owner"), details)
    csv_file(directory / "by-resource.csv", ("stage", "reason", "resource", "itemCount", "itemIds"), (
        dict(stage=s, reason=r, resource=p, itemCount=len(group), itemIds=";".join(sorted(group, key=int)))
        for (s, r, p), group in sorted(paths.items(), key=lambda kv: (-len(kv[1]), kv[0]))))
    summary = dict(itemVersion=audit["itemVersion"], resourceVersion=audit["resourceVersion"],
                   itemsSha256=audit["itemsSha256"], sdkWasmSha256=report["sdkWasmSha256"],
                   total=len(items), failedItems=len(failed), outcomes=by_outcome,
                   failedItemsByKind=Counter(r["kind"] for r in failed),
                   affectedItemsByReason={k: len(v) for k,v in sorted(reasons.items(), key=lambda kv: -len(kv[1]))})
    (directory / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    build(Path(sys.argv[1]))
