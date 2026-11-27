"""Prepare quest catalog pages, detail chunks and the client-side quest index."""

import hashlib
import json
from collections import defaultdict
from pathlib import Path

SECTION_ORDER = {
    "main": 0, "chronicle": 1, "side": 2, "job": 3,
    "beast": 4, "season": 5, "other": 6, "unknown": 7,
}
SECTION_LABEL = {
    "main": "主线", "chronicle": "编年史", "side": "支线", "job": "职业",
    "beast": "蛮族", "season": "季节活动", "other": "其他", "unknown": "未分类",
}
SECTION_SHORT = {
    "main": "主", "chronicle": "编", "side": "支", "job": "职",
    "beast": "蛮", "season": "季", "other": "其", "unknown": "未",
}
PAGE_SIZE = 100
CHUNK = 500
NODE_W, NODE_H, NODE_STEP = 158, 56, 185
GRAPH_MARGIN = 8


def section_of(category):
    if not category:
        return "unknown"
    raw = category.get("section", "255")
    if raw in ("0", "1"):
        return "main"
    if raw == "2":
        return "chronicle"
    if raw == "3":
        return "side"
    if raw in ("4", "5"):
        return "beast"
    if raw == "6":
        return "job"
    if raw == "7":
        return "season" if category.get("name") == "季节活动" else "other"
    return "unknown"


def pagination_links(page, page_count):
    def path(number):
        return "/quests/index.html" if number == 1 else f"/quests/page/{number}.html"

    numbers = []
    visible = {1, page_count}
    start = max(1, min(page - 2, page_count - 4))
    visible.update(range(start, min(page_count, start + 5) + 1))
    last = 0
    for number in sorted(visible):
        if number - last == 2:
            numbers.append([str(number - 1), path(number - 1)])
        elif number - last > 2:
            numbers.append(["…", ""])
        numbers.append([str(number), "" if number == page else path(number)])
        last = number
    return numbers


def item_ref(item_id, count, items):
    item = items.get(item_id)
    return [str(item_id), item["name"], count, str(item["icon"])] if item else [
        "", f"物品 #{item_id}（未收录）", count, "0"]


def series_key(quest, genres):
    genre = quest.get("genre") or 0
    if genre and str(genre) in genres:
        return f"g{genre}", genres[str(genre)]["name"]
    category = quest.get("category") or 0
    return f"c{category}", "未分类"


def graph_for(quest, by_id, prev, next_ids, series_rows, series_index):
    # Series window.  Short series fit completely; long MSQ chapters show a
    # five-quest window around the current quest.
    if len(series_rows) <= 12:
        window = [row["id"] for row in series_rows]
    else:
        start = max(0, series_index - 2)
        window = [row["id"] for row in series_rows[start:start + 5]]
    if quest["id"] not in window:
        window.insert(0, quest["id"])
    main = [by_id[quest_id] for quest_id in window if quest_id in by_id]
    main_ids = {row["id"] for row in main}

    prev_nodes = [by_id[quest_id] for quest_id in prev if quest_id in by_id and quest_id not in main_ids]
    next_all = [by_id[quest_id] for quest_id in next_ids if quest_id in by_id and quest_id not in main_ids]
    next_nodes = next_all[:3]
    more_next = len(next_all) - len(next_nodes)

    nodes = []
    has_prev = bool(prev_nodes[:5])
    has_next = bool(next_nodes or more_next)
    prev_y = 70 if has_prev else 0
    main_y = 220 if has_prev else 70
    next_y = (340 if has_prev else 190) if has_next else 0

    def add(row, role, x, y, href=True):
        nodes.append({
            "id": row["id"], "name": row["name"], "level": row["level"],
            "x": x, "y": y, "role": role,
            "href": f"/quests/{row['id']}.html" if href else "",
        })

    for index, row in enumerate(prev_nodes[:5]):
        add(row, "prev", GRAPH_MARGIN + index * NODE_STEP, prev_y)
    for index, row in enumerate(main):
        add(row, "current" if row["id"] == quest["id"] else "series",
            GRAPH_MARGIN + index * NODE_STEP, main_y)
    for index, row in enumerate(next_nodes):
        add(row, "next", GRAPH_MARGIN + index * NODE_STEP, next_y)
    if more_next:
        nodes.append({
            "id": "more", "name": f"还有 {more_next} 个后续", "level": "",
            "x": GRAPH_MARGIN + len(next_nodes) * NODE_STEP, "y": next_y,
            "role": "more", "href": "",
        })

    edges = []
    for left, right in zip(main, main[1:]):
        edges.append([left["id"], right["id"], "series"])
    existing = {(a, b) for a, b, _ in edges}
    main_index = {row["id"]: index for index, row in enumerate(main)}
    for prev_id in prev:
        if prev_id in main_index and main_index.get(prev_id, -2) + 1 != main_index.get(quest["id"]):
            if (prev_id, quest["id"]) not in existing:
                edges.append([prev_id, quest["id"], "prev"])
                existing.add((prev_id, quest["id"]))
    for next_id in next_ids:
        if next_id in main_index and main_index.get(next_id) != main_index.get(quest["id"], -2) + 1:
            if (quest["id"], next_id) not in existing:
                edges.append([quest["id"], next_id, "next"])
                existing.add((quest["id"], next_id))
    for row in prev_nodes[:5]:
        edges.append([row["id"], quest["id"], "prev"])
    for row in next_nodes:
        edges.append([quest["id"], row["id"], "next"])
    if more_next:
        edges.append([quest["id"], "more", "more"])

    width = max(560, GRAPH_MARGIN + max(len(prev_nodes[:5]), len(main), len(next_nodes) + (1 if more_next else 0)) * NODE_STEP + NODE_W)
    return {
        "width": width,
        "height": max(main_y, prev_y, next_y) + NODE_H + 8,
        "nodes": nodes,
        "edges": edges,
        "moreNext": more_next,
        "join": "or" if quest.get("prevJoin") == 2 else "and",
    }


def prepare_quests(*, root, records, emit_json):
    source_path = root / "sources/quests.json"
    if not source_path.is_file():
        print("skip quests (missing sources/quests.json)")
        return None

    snapshot = json.loads(source_path.read_text(encoding="utf-8"))
    quests = snapshot["quests"]
    by_id = {quest["id"]: quest for quest in quests}
    genres = snapshot.get("genres", {})
    categories = snapshot.get("categories", {})
    places = snapshot.get("places", {})
    npcs = snapshot.get("npcs", {})
    expansions = snapshot.get("expansions", {})
    items = {item["id"]: item for item in records}

    for quest in quests:
        genre = genres.get(str(quest.get("genre") or 0))
        category = categories.get(str(genre["category"])) if genre else categories.get(str(quest.get("category") or 0))
        quest["category"] = int(genre["category"]) if genre else 0
        quest["categoryName"] = category["name"] if category else "未分类"
        quest["genreName"] = genre["name"] if genre else "未分类"
        quest["section"] = section_of(category)
        quest["placeName"] = places.get(str(quest.get("place") or 0), "")
        quest["expansionName"] = expansions.get(str(quest.get("expansion") or 0), "未分类")
        quest["issuerName"] = npcs.get(str(quest.get("issuer") or 0), "")
        quest["targetName"] = npcs.get(str(quest.get("target") or 0), "")
        quest["beastName"] = snapshot.get("beastTribes", {}).get(str(quest.get("beast") or 0), "")
        quest["festivalName"] = snapshot.get("festivals", {}).get(str(quest.get("festival") or 0), "")

    next_map = defaultdict(list)
    for quest in quests:
        quest["prev"] = [quest_id for quest_id in quest["prev"] if quest_id in by_id]
        for prev_id in quest["prev"]:
            next_map[prev_id].append(quest["id"])
    for quest in quests:
        quest["next"] = sorted(set(next_map.get(quest["id"], [])), key=lambda quest_id: (by_id[quest_id]["sort"], quest_id))

    # Series are genre-first.  Unclassified quests fall back to their journal
    # category so they still get a useful ordering.
    series_members = defaultdict(list)
    for quest in quests:
        key, _ = series_key(quest, genres)
        quest["seriesKey"] = key
        series_members[key].append(quest)
    for key, members in series_members.items():
        members.sort(key=lambda quest: (quest["sort"] or 10**9, quest["id"]))
        for index, quest in enumerate(members):
            quest["seriesIndex"] = index
            quest["seriesTotal"] = len(members)

    detail_rows = []
    for position, quest in enumerate(quests):
        series_rows = series_members[quest["seriesKey"]]
        if quest["seriesKey"] == "c0":
            series_rows = [quest]
        if len(series_rows) <= 12:
            series_window = series_rows
        else:
            start = max(0, quest["seriesIndex"] - 2)
            series_window = series_rows[start:start + 5]
        prev_rows = [by_id[quest_id] for quest_id in quest["prev"]]
        next_rows = [by_id[quest_id] for quest_id in quest["next"]]
        graph = graph_for(quest, by_id, quest["prev"], quest["next"], series_rows, quest["seriesIndex"])
        rewards = quest.get("rewards", {})
        detail_rows.append({
            "id": str(quest["id"]),
            "name": quest["name"],
            "level": str(quest["level"]),
            "level2": str(quest.get("level2") or ""),
            "expansion": quest["expansionName"],
            "section": quest["section"],
            "sectionLabel": SECTION_LABEL[quest["section"]],
            "sectionShort": SECTION_SHORT[quest["section"]],
            "category": str(quest["category"]),
            "categoryName": quest["categoryName"],
            "genre": str(quest.get("genre") or 0),
            "genreName": quest["genreName"],
            "place": str(quest.get("place") or 0),
            "placeName": quest["placeName"],
            "sort": str(quest.get("sort") or 0),
            "eventIcon": str(quest.get("event") or 0),
            "icon": str(quest.get("icon") or 0),
            "repeatable": bool(quest.get("repeatable")),
            "issuer": str(quest.get("issuer") or 0),
            "issuerName": quest["issuerName"],
            "target": str(quest.get("target") or 0),
            "targetName": quest["targetName"],
            "beastName": quest["beastName"],
            "festivalName": quest["festivalName"],
            "prev": [[str(row["id"]), row["name"], str(row["level"])] for row in prev_rows],
            "next": [[str(row["id"]), row["name"], str(row["level"])] for row in next_rows],
            "nextShow": [[str(row["id"]), row["name"], str(row["level"])] for row in next_rows[:8]],
            "nextMore": max(0, len(next_rows) - 8),
            "seriesWindow": [[str(row["id"]), row["name"], str(row["level"])] for row in series_window],
            "prevJoin": "or" if quest.get("prevJoin") == 2 else "and",
            "lock": [[str(prev_id), by_id[prev_id]["name"]] for prev_id in quest.get("lock", []) if prev_id in by_id],
            "rewards": {
                "gil": str(rewards.get("gil") or 0),
                "exp": str(rewards.get("exp") or 0),
                "items": [item_ref(item_id, count, items) for item_id, count in rewards.get("items", [])],
                "optional": [item_ref(item_id, count, items) for item_id, count in rewards.get("optional", [])],
                "emote": str(rewards.get("emote") or 0),
                "action": str(rewards.get("action") or 0),
                "other": str(rewards.get("other") or 0),
            },
            "series": {
                "key": quest["seriesKey"],
                "slug": quest["seriesKey"],
                "name": quest["genreName"],
                "index": 0 if quest["seriesKey"] == "c0" else quest["seriesIndex"],
                "total": 1 if quest["seriesKey"] == "c0" else quest["seriesTotal"],
            },
            "summary": quest["steps"][0] if quest["steps"] else "",
            "steps": quest["steps"][1:],
            "graph": json.dumps(graph, ensure_ascii=False, separators=(",", ":")),
        })

    # Client-side index and facets.
    index_rows = []
    for quest in quests:
        rewards = quest.get("rewards", {})
        index_rows.append([
            quest["id"], quest["name"], quest["section"], quest["category"],
            quest["genre"], quest["level"], quest["expansion"],
            quest.get("place") or 0, quest.get("sort") or 0, quest.get("event") or 0,
            rewards.get("gil") or 0, rewards.get("exp") or 0,
            len(rewards.get("items", [])),
        ])

    categories_out = {}
    for quest in quests:
        key = str(quest["category"])
        if key not in categories_out:
            categories_out[key] = [quest["categoryName"], quest["section"], 0]
        categories_out[key][2] += 1
    used_places = {str(quest.get("place") or 0) for quest in quests}
    filters = {
        "sections": [[key, SECTION_LABEL[key], sum(1 for quest in quests if quest["section"] == key)]
                     for key in sorted(SECTION_ORDER, key=SECTION_ORDER.get)],
        "categories": categories_out,
        "genres": {str(quest["genre"]): [quest["genreName"], quest["category"]] for quest in quests},
        "places": {key: places[key] for key in places if key in used_places},
        "expansions": expansions,
        "levels": [min(quest["level"] for quest in quests), max(quest["level"] for quest in quests)],
        "count": len(quests),
    }

    private = root / "content/.data/quests"
    import shutil
    shutil.rmtree(private, ignore_errors=True)

    chunks = list(range(0, len(detail_rows), CHUNK))
    for chunk, start in enumerate(chunks):
        emit_json(private / "chunks" / f"{chunk}.json", detail_rows[start:start + CHUNK])

    # Static no-JS catalog pages, ordered like the story view.
    story_rows = sorted(quests, key=lambda quest: (
        SECTION_ORDER[quest["section"]], quest["categoryName"], quest["sort"] or 10**9, quest["id"]))
    page_count = max(1, (len(story_rows) + PAGE_SIZE - 1) // PAGE_SIZE)
    for page in range(1, page_count + 1):
        rows = [[str(quest["id"]), quest["name"], quest["categoryName"],
                 str(quest["level"]), quest["placeName"]]
                for quest in story_rows[(page - 1) * PAGE_SIZE:page * PAGE_SIZE]]
        emit_json(private / "catalog" / f"page-{page}.json", {
            "count": len(story_rows),
            "pageSize": PAGE_SIZE,
            "label": f"第 {page} / {page_count} 页",
            "previous": "/quests/index.html" if page == 2 else f"/quests/page/{page - 1}.html" if page > 2 else "",
            "next": f"/quests/page/{page + 1}.html" if page < page_count else "",
            "pagination": pagination_links(page, page_count),
            "items": rows,
        })

    # One static page per series with at least two quests.
    series_out = []
    for key, members in sorted(series_members.items()):
        if len(members) < 2 or key.startswith("g0") or key == "c0":
            continue
        name = members[0]["genreName"]
        series_out.append({
            "slug": key,
            "name": name,
            "total": len(members),
            "section": members[0]["section"],
            "rows": [[str(row["id"]), row["name"], str(row["level"]), row["placeName"],
                      str(row["sort"]), row["categoryName"]] for row in members],
        })

    payload = (source_path.read_bytes() + json.dumps(filters, ensure_ascii=False, sort_keys=True).encode())
    asset_path = "generated/quests-" + hashlib.sha256(payload).hexdigest()[:16]
    assets = root / "static" / asset_path
    emit_json(assets / "index.json", index_rows)
    emit_json(assets / "filters.json", filters)

    catalog = {
        "count": len(quests),
        "pageSize": PAGE_SIZE,
        "pageCount": page_count,
        "assetPath": asset_path,
        "source": snapshot.get("source", {}),
        "items": [quest["id"] for quest in quests],
        "titles": {str(quest["id"]): quest["name"] for quest in quests},
        "series": [[entry["slug"], entry["name"], entry["total"]] for entry in series_out],
    }
    emit_json(private / "catalog.json", catalog)
    for entry in series_out:
        emit_json(private / "series" / f"{entry['slug']}.json", entry)
    print(f"Prepared {len(quests)} quests, {page_count} catalog pages and {len(series_out)} series")
    return catalog
