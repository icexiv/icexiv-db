"""Import verified equipment families from xiv-companion's collection catalog."""
import json
from pathlib import Path
import sys


def build(catalog, exported):
    items = {i["id"]: i for i in json.loads(exported.read_bytes())}
    groups = {}
    for entry in json.loads(catalog.read_bytes())["items"]:
        key = entry.get("setId")
        item = items.get(entry["id"])
        if not key or not entry.get("setName") or entry["kind"] != "equipment" or not item:
            continue
        if (item["name"], item["category"], item["equipLevel"]) != (
                entry["name"], entry["itemUiCategory"], entry["levelEquip"]):
            continue
        groups.setdefault(key, [entry["setName"], []])[1].append(item["id"])
    return {"groups": [g for g in groups.values() if len(g[1]) > 1]}


if __name__ == "__main__":
    from scripts.pipeline import bundle
    bundle.merge(bundle.REFERENCE, {"sets": build(*map(Path, sys.argv[1:]))})
