"""Map unlock items to their ActionTimeline rows from datamining CSVs.

Emote items carry ItemAction.Type 2633; Data[2] is the Emote row, whose
ActionTimeline columns point at the timelines. The output is bound to the item
export digest, like the other snapshots.
"""
import csv
import hashlib
import json
from pathlib import Path
import sys

EMOTE_TYPE = 2633


def rows(path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        next(reader)
        names = next(reader)
        next(reader)
        for row in reader:
            yield names, dict(zip(names, row))


def build(items_csv, actions_csv, emotes_csv, timelines_csv, exported):
    raw = exported.read_bytes()
    items = {i["id"] for i in json.loads(raw)}
    actions = {r["#"]: r for _, r in rows(actions_csv)}
    emotes = {r["#"]: r for _, r in rows(emotes_csv)}
    timelines = {r["#"]: r["Key"] for _, r in rows(timelines_csv)}
    mapped = {}
    for _, item in rows(items_csv):
        if not item["Name"] or item["#"] == "0" or int(item["#"]) not in items:
            continue
        action = actions.get(item["ItemAction"])
        if not action or action["Type"] != str(EMOTE_TYPE):
            continue
        emote = emotes.get(action["Data[2]"])
        if not emote:
            continue
        keys = []
        for column in emote:
            if column.startswith("ActionTimeline[") and int(emote[column]):
                row = emote[column]
                key = timelines.get(row)
                if key:
                    keys.append([row, key])
        if keys:
            mapped[item["#"]] = dict(emote=action["Data[2]"], timelines=keys)
    return {"itemsSha256": hashlib.sha256(raw).hexdigest(), "items": mapped}


if __name__ == "__main__":
    from scripts.pipeline import bundle
    result = build(*map(Path, sys.argv[1:]))
    bundle.merge(bundle.DATAMINING, {"itemsSha256": result["itemsSha256"],
                                     "actions": bundle.facet(result)})
    print(f"Mapped {len(result['items'])} items")
