"""Prepare pure manifest data for Notist and browser search/recipe/relation shards.

Zero asset URL coupling: stores only logical IDs (icon ID, portrait image ID,
and media availability flags). Concrete asset URLs (disabled / local / remote)
are resolved later at ``notist serve`` / ``notist build`` time.
"""

import json
import re
import shutil

if __package__:
    from .export_loader import (
        CATEGORIES, ITEM_CHUNK, ROOT,
        catalog_metadata, catalog_pages, category_name, load_export, write_json,
    )
    from .recipe_data import write_recipe_and_relations
else:
    from export_loader import (
        CATEGORIES, ITEM_CHUNK, ROOT,
        catalog_metadata, catalog_pages, category_name, load_export, write_json,
    )
    from recipe_data import write_recipe_and_relations


def _read(root, rel_path):
    path = root / rel_path
    return json.loads(path.read_bytes()) if path.is_file() else {}


def _build_relations(records, by_id, families, peers, versions):
    family_members, named_families = {}, {}
    for name, ids in families:
        named_families.setdefault(name, []).append(ids)
        for i in ids:
            family_members.setdefault(i, []).append((name, ids))

    relation_keys = {}
    relation_tables = []

    def group_key(title, ids, current):
        members = tuple(j for j in ids if j in by_id)
        if not any(j != current for j in members):
            return None
        identity = (title, members)
        if identity not in relation_keys:
            key = len(relation_tables)
            relation_keys[identity] = key
            rows = [[str(j), by_id[j]["name"], by_id[j]["icon"], category_name(by_id[j]),
                     versions.get(j, "未归档")] for j in members]
            relation_tables.append([str(key), title, rows])
        return relation_keys[identity]

    def relations_for(item):
        i = item["id"]
        found = []
        for name, ids in family_members.get(i, []):
            key = group_key("同套装装备 · " + name, ids, i)
            if key is not None:
                found.append([key, "同套装装备 · " + name])
        if item["category"] == 112 and i not in family_members:
            variants = named_families.get(item["name"], [])
            labels = []
            for members in variants:
                suffixes = {m[0].lstrip("·") if (m := re.search(r"(?:\+\d+|·[^·+]+)$", by_id[j]["name"])) else "普通版"
                            for j in members if j in by_id}
                labels.append(suffixes.pop() if len(suffixes) == 1 else None)
            for n, members in enumerate(variants):
                title = "套装相关装备"
                if len(variants) > 1:
                    label = labels[n]
                    title += " · " + (label if label and labels.count(label) == 1 else f"第 {n + 1} 组")
                key = group_key(title, members, i)
                if key is not None:
                    found.append([key, title])
        if i in peers:
            key = group_key("同模型装备", peers[i], i)
            if key is not None:
                found.append([key, "同模型装备"])
        return found

    by_item = {item["id"]: relations_for(item) for item in records}
    return by_item, relation_tables


def prepare(input_path, *, root=ROOT, emit_json=write_json):
    export, records, digest = load_export(input_path, root=root)
    items_sha = export["itemsSha256"]
    (root / "content/.data/prepared.json").unlink(missing_ok=True)

    # This namespace belongs exclusively to this preparation script.
    shutil.rmtree(root / "static/generated", ignore_errors=True)

    batch = _read(root, "sources/datamining.json")
    reference = _read(root, "sources/reference.json")
    models = _read(root, "sources/model-library.json")
    actions = _read(root, "sources/action-library.json")
    if batch.get("itemsSha256") not in (None, items_sha):
        print("note: sources/datamining.json is from another Item batch; using it as-is")

    gear_snapshot = batch.get("equipment", {})
    gear = {i: [level, slot, job] for first, last, level, slot, job in gear_snapshot.get("ranges", [])
            for i in range(first, last + 1)}
    releases = reference.get("releases", {})
    versions = {i: releases["labels"][label] for first, last, label in releases.get("ranges", [])
                for i in range(first, last + 1)}
    unlocks = batch.get("unlocks", {}).get("groups", {})
    families = reference.get("sets", {}).get("groups", [])
    recipes = batch.get("recipes", {})
    books = recipes.get("books", {})
    crafting = recipes.get("byResult", {})
    peers = {i: ids for ids in models.get("groups", []) for i in ids}
    kits = batch.get("portraits", {}).get("kits", {})
    music_ids = {int(i) for i in batch.get("orchestrion", {}).get("tracks", {})}
    model_ids = {int(i) for i in models.get("items", {})}
    action_ids = {int(i) for i in actions.get("items", {})}

    by_id = {i["id"]: i for i in records}
    relations_by_item, relation_tables = _build_relations(records, by_id, families, peers, versions)

    uses = {}
    for result, formulas in crafting.items():
        for recipe, craft, _, ingredients in formulas:
            for material, amount in ingredients:
                uses.setdefault(material, {}).setdefault(result, []).append([str(recipe), craft, str(amount)])

    catalog = catalog_metadata(export, digest, len(records), root=root)
    asset_path = catalog["assetPath"]
    assets = root / "static" / asset_path

    counts = write_recipe_and_relations(assets, by_id, books, crafting, uses,
                                        relation_tables, emit_json)

    previews = {}
    for id_, sections in kits.items():
        if sections:
            image = next((p[2] for rows in sections.values() for p in rows if p[2]), 0)
            previews[id_] = [image, " · ".join(f"{kind} {len(rows)} 件" for kind, rows in sections.items())]

    emit_json(assets / "filters.json", {
        "categories": CATEGORIES, "sets": families, "releaseOrder": releases.get("labels", []),
        "unlocks": unlocks, "portraits": previews, "slots": gear_snapshot.get("slots", {}),
        "jobs": gear_snapshot.get("members", {}),
    })
    emit_json(assets / "index.json", [[
        i["id"], i["name"], i["category"], i["icon"], i["equipLevel"],
        *gear.get(i["id"], [None] * 3), versions.get(i["id"], "未归档"),
        int(not i["untradable"]),
        int(str(i["id"]) in crafting) if "byResult" in recipes else None,
    ] for i in records])

    pages = catalog_pages(records, export["source"])
    private = root / "content/.data"
    shutil.rmtree(private, ignore_errors=True)

    for chunk, start in enumerate(range(0, len(records), ITEM_CHUNK)):
        details = []
        for item in records[start:start + ITEM_CHUNK]:
            details.append(_item_record(
                item, gear, gear_snapshot, versions, counts,
                kits, previews, relations_by_item,
                music_ids, model_ids, action_ids,
            ))
        emit_json(private / "items" / f"{chunk}.json", details)

    for page, record in enumerate(pages, 1):
        emit_json(private / "catalog" / f"page-{page}.json", record)

    # The build reads only this directory: routes plus the catalog identity.
    emit_json(private / "catalog.json", dict(catalog, items=[item["id"] for item in records]))
    # Publish the receipt last: incomplete preparation must not be used by a build.
    emit_json(private / "prepared.json", {"assetPath": asset_path})
    print(f"Prepared {len(records)} item records and {len(pages)} catalog pages")


def _item_record(item, gear, gear_snapshot, versions, counts, kits, previews,
                 relations, music_ids, model_ids, action_ids):
    i = item["id"]
    extra = gear.get(i)
    item_counts = counts.get(i, {})
    kit_status, sections = "", []
    kit = kits.get(str(i))
    if kit is not None:
        kit_status = "已收录" if str(i) in previews else "未匹配"
        if kit_status == "已收录":
            sections = [[group, [[title, label, str(image) if image else ""]
                                 for title, label, image in parts]]
                        for group, parts in kit.items()]
    return {
        "id": str(i),
        "name": item["name"],
        "description": item["description"],
        "category": str(item["category"]),
        "kind": category_name(item),
        "searchCategory": str(item["searchCategory"]),
        "equipLevel": str(item["equipLevel"]),
        "rarity": str(item["rarity"]),
        "stackSize": str(item["stackSize"]),
        "unique": "是" if item["unique"] else "否",
        "untradable": "是" if item["untradable"] else "否",
        "hq": "是" if item["hq"] else "否",
        "icon": str(item["icon"]),
        "version": versions.get(i, "未归档"),
        "ilvl": str(extra[0]) if extra else "",
        "slots": "、".join(gear_snapshot["slots"][str(extra[1])]) if extra else "",
        "jobs": gear_snapshot["jobLabels"][str(extra[2])] if extra else "",
        "ingredientCount": item_counts.get("ingredientCount", 0),
        "bookCount": item_counts.get("bookCount", 0),
        "useCount": item_counts.get("useCount", 0),
        "kitStatus": kit_status,
        "kitSections": sections,
        "relations": relations.get(i, []),
        "hasOrchestrion": i in music_ids,
        "hasModel": i in model_ids,
        "hasAction": i in action_ids,
    }
