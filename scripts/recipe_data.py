"""Write the recipe and relation shards the detail page loads on demand.

Pure manifest data: stores integer icon IDs (never concrete URLs), so shards
never change when switching asset sources (disabled / local / CDN).

Recipe panel layout (per item, keyed by item id in ``panels``):
  ingredients: [[recipe, craft, yield, [[material, qty], ...]], ...]
  book:        [[recipe, product, qty], ...]
  uses:        [[recipe, craft, product, qty], ...]
Each shard also embeds ``items`` = {id: [name, iconId, kind]} for every item it
references, so a single request renders every card.
"""

if __package__:
    from .export_loader import RECIPE_SHARD, RELATIONS_PER_SHARD, category_name
else:
    from export_loader import RECIPE_SHARD, RELATIONS_PER_SHARD, category_name


def write_recipe_and_relations(assets, by_id, books, crafting, uses, relation_tables, emit_json):
    """Write ``recipes/<shard>.json`` and ``relations/<shard>.json``; return per-item counts."""
    shards, counts = {}, {}
    for item_id in sorted(by_id):
        key = str(item_id)
        panels = {}
        formulas = crafting.get(key)
        if formulas:
            panels["ingredients"] = [[rid, craft, amount, [[m, qty] for m, qty in ingredients]]
                                     for rid, craft, amount, ingredients in formulas]
        rows = books.get(key)
        if rows:
            panels["book"] = [[rid, product, qty] for rid, product, qty in rows]
        products = uses.get(item_id)
        if products:
            panels["uses"] = [[int(rid), craft, int(product), qty]
                              for product, recipes in products.items() for rid, craft, qty in recipes]
        if not panels:
            continue
        counts[item_id] = {
            "ingredientCount": len(formulas or []),
            "bookCount": len(rows or []),
            "useCount": len(products or {}),
        }
        shards.setdefault(item_id // RECIPE_SHARD, {})[key] = panels

    for shard, panels in sorted(shards.items()):
        referenced = set()
        for panel in panels.values():
            for _, _, _, ingredients in panel.get("ingredients", []):
                referenced.update(material for material, _ in ingredients)
            for _, product, _ in panel.get("book", []):
                referenced.add(product)
            for _, _, product, _ in panel.get("uses", []):
                referenced.add(product)
        items = {}
        for i in sorted(referenced):
            record = by_id.get(i)
            if record is not None:
                items[str(i)] = [record["name"], record["icon"], category_name(record)]
        emit_json(assets / "recipes" / f"{shard}.json", {"items": items, "panels": panels})

    for offset in range(0, len(relation_tables), RELATIONS_PER_SHARD):
        emit_json(assets / "relations" / f"{offset // RELATIONS_PER_SHARD}.json",
                  relation_tables[offset:offset + RELATIONS_PER_SHARD])

    return counts
