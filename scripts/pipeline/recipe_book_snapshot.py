"""Index CHS recipes by result item and by master recipe book."""
import hashlib
import json
from pathlib import Path
import sys

if __package__:
    from .unlock_snapshot import sheet
else:
    from unlock_snapshot import sheet


def build(items_csv, actions_csv, recipes_csv, exported):
    raw = exported.read_bytes()
    names = {item["id"]: item["name"] for item in json.loads(raw)}
    actions = {row["#"]: int(row["Data[0]"]) for row in sheet(actions_csv) if row["Type"] == "2136"}
    books = {}
    for row in sheet(items_csv):
        key = actions.get(row["ItemAction"])
        if key and row["Name"]:
            item = int(row["#"])
            if names.get(item) != row["Name"] or key in books:
                raise ValueError(f"Invalid recipe book mapping: {key} -> {item}")
            books[key] = item
    contents = {}
    by_result = {}
    crafts = ["刻木匠", "锻铁匠", "铸甲匠", "雕金匠", "制革匠", "裁衣匠", "炼金术士", "烹调师"]
    for row in sheet(recipes_csv):
        key, result = int(row["SecretRecipeBook"]), int(row["Item{Result}"])
        if not result:
            continue
        if result not in names:
            raise ValueError(f"Unknown result item: {result}")
        recipe, yield_ = int(row["#"]), int(row["Amount{Result}"])
        ingredients = []
        for slot in range(8):
            amount = int(row[f"Amount{{Ingredient}}[{slot}]"])
            if amount:
                item = int(row[f"Item{{Ingredient}}[{slot}]"])
                if item not in names:
                    raise ValueError(f"Unknown ingredient {item} in recipe {recipe}")
                ingredients.append([item, amount])
        by_result.setdefault(result, []).append([recipe, crafts[int(row["CraftType"])], yield_, ingredients])
        if key:
            contents.setdefault(books[key], []).append([recipe, result, yield_])
    return {"itemsSha256": hashlib.sha256(raw).hexdigest(), "books": contents, "byResult": by_result}


if __name__ == "__main__":
    from scripts.pipeline import bundle
    snapshot = build(*map(Path, sys.argv[1:]))
    bundle.merge(bundle.DATAMINING, {"itemsSha256": snapshot["itemsSha256"],
                                     "recipes": bundle.facet(snapshot)})
