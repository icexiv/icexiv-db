"""Prepare a reviewed lookup from CHS datamining CSVs for one exact Item export.

Usage: python3 scripts/pipeline/equipment_snapshot.py CSV_DIRECTORY inputs/game-export/items.json
"""
import csv
import hashlib
import json
from pathlib import Path
import sys


def sheet(directory, name):
    with (directory / f"{name}.csv").open(encoding="utf-8-sig", newline="") as f:
        rows = csv.reader(f)
        next(rows)
        header = next(rows)
        next(rows)
        return [dict(zip(header, row)) for row in rows]


def build(directory, exported):
    raw = exported.read_bytes()
    items = {i["id"]: i for i in json.loads(raw)}
    jobs = {int(r["#"]): r["Name"] for r in sheet(directory, "ClassJob") if r["Name"] and int(r["#"])}
    groups = {}
    for row in sheet(directory, "ClassJobCategory"):
        # Membership columns follow ClassJob row order (including adventurer).
        groups[int(row["#"])] = row["Name"]
    with (directory / "ClassJobCategory.csv").open(encoding="utf-8-sig") as f:
        members = {r[0]: [name for j, name in jobs.items() if r[2+j] == "True"]
                   for r in list(csv.reader(f))[3:]}
    slot_names = ["主手", "副手", "头部", "身体", "手部", "腰部", "腿部", "脚部", "耳部", "颈部", "腕部", "手指", "手指", "灵魂水晶"]
    slots = {r["#"]: list(dict.fromkeys(n for n, v in zip(slot_names, list(r.values())[1:]) if v == "1"))
             for r in sheet(directory, "EquipSlotCategory")}
    ranges = []
    for r in sheet(directory, "Item"):
        if not r["Name"] or r["#"] == "0":
            continue
        i = items.pop(int(r["#"]))
        if (r["Name"], int(r["ItemUICategory"]), int(r["Level{Equip}"]), int(r["Icon"])) != (
                i["name"], i["category"], i["equipLevel"], i["icon"]):
            raise ValueError(f"Item mismatch: {i['id']}")
        slot = int(r["EquipSlotCategory"])
        if not slot:
            continue
        values = [int(r["Level{Item}"]), slot, int(r["ClassJobCategory"])]
        if ranges and ranges[-1][1] == i["id"] - 1 and ranges[-1][2:] == values:
            ranges[-1][1] = i["id"]
        else:
            ranges.append([i["id"], i["id"], *values])
    if items:
        raise ValueError("Item CSV incomplete")
    return dict(itemsSha256=hashlib.sha256(raw).hexdigest(), slots=slots, members=members,
                jobLabels=groups, ranges=ranges)


if __name__ == "__main__":
    from scripts.pipeline import bundle
    result = build(Path(sys.argv[1]), Path(sys.argv[2]))
    bundle.merge(bundle.DATAMINING, {"itemsSha256": result["itemsSha256"],
                                     "equipment": bundle.facet(result)})
