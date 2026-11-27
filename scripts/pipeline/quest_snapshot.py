"""Build a Chinese-only quest snapshot from the CN datamining CSV and quest text.

The CN ``Quest.csv`` uses the three-row datamining header, but the trailing
reward/classification block in each data row is shifted 128 columns to the
right of its header names.  We read those fields with the recorded offset and
keep the offset in the snapshot so a future schema change fails loudly in
``validate`` instead of silently returning defaults.

Usage:
    python3 scripts/pipeline/quest_snapshot.py \
        --quest-csv /path/to/Quest.csv \
        --text-dir /path/to/extracted/quest \
        --data-dir /path/to/csv-root \
        --items inputs/game-export/items.json \
        --commit <datamining-commit> \
        --output sources/quests.json
"""

import argparse
import csv
import hashlib
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TAIL_OFFSET = 128
TAIL_START = 1439  # Level{Max}; every field from here on is shifted.

# Header index -> field.  For indices >= TAIL_START the data index is +128.
FIELDS = {
    "id": "#",
    "name": "Name",
    "expansion": "Expansion",
    "class_job_level": "ClassJobLevel[0]",
    "class_job_level_2": "ClassJobLevel[1]",
    "previous_quest_join": "PreviousQuestJoin",
    "quest_lock_join": "QuestLockJoin",
    "issuer_start": "Issuer{Start}",
    "issuer_location": "Issuer{Location}",
    "target_end": "Target{End}",
    "is_repeatable": "IsRepeatable",
    "repeat_interval": "RepeatIntervalType",
    "type": "Type",
    "festival": "Festival",
    "festival_begin": "FestivalBegin",
    "festival_end": "FestivalEnd",
    "beast_tribe": "BeastTribe",
    "beast_rank": "BeastReputationRank",
    "level_max": "Level{Max}",
    "class_job_required": "ClassJob{Required}",
    "reward_other_display": "QuestRewardOtherDisplay",
    "exp_factor": "ExpFactor",
    "gil_reward": "GilReward",
    "emote_reward": "Emote{Reward}",
    "action_reward": "Action{Reward}",
    "other_reward": "Other{Reward}",
    "place_name": "PlaceName",
    "journal_genre": "JournalGenre",
    "icon": "Icon",
    "event_icon_type": "EventIconType",
    "sort_key": "SortKey",
    "hide_offer_icon": "HideOfferIcon",
}

ARRAYS = {
    "previous_quest": "PreviousQuest[{i}]",
    "quest_lock": "QuestLock[{i}]",
    "instance_content": "InstanceContent[{i}]",
    "item_reward": "Item{Reward}[{i}]",
    "item_count_reward": "ItemCount{Reward}[{i}]",
    "optional_item_reward": "OptionalItem{Reward}[{i}]",
    "optional_item_count_reward": "OptionalItemCount{Reward}[{i}]",
}

EXPANSIONS = {
    0: "重生之境",
    1: "苍穹之禁城",
    2: "红莲之狂潮",
    3: "暗影之逆焰",
    4: "晓月之终途",
    5: "金曦之遗辉",
}


def read_csv(path):
    with open(path, encoding="utf-8-sig", newline="") as stream:
        return list(csv.reader(stream))


def header_columns(rows):
    """Return (name -> header index) for the CN three-row CSV header."""
    head = rows[1]
    return {name: index for index, name in enumerate(head) if name}


def cell(row, columns, name):
    """Read a field, applying the CN CSV's tail offset where needed."""
    index = columns[name]
    if index >= TAIL_START:
        index += TAIL_OFFSET
    return row[index] if index < len(row) else ""


def number(row, columns, name):
    value = cell(row, columns, name).strip()
    try:
        return int(value) if value else 0
    except ValueError:
        return 0


def truth(row, columns, name):
    return cell(row, columns, name).strip().lower() == "true"


def field_name(template, index):
    return template.replace("{i}", str(index))


def array(row, columns, template, count):
    return [number(row, columns, field_name(template, i)) for i in range(count)]


def clean_step(text, item_names):
    """Turn quest journal markup into readable text for the static page."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    def sheet(match):
        item_id = match.group(1)
        return "「" + item_names.get(item_id, "物品 #" + item_id) + "」"

    text = re.sub(r"<Sheet\(Item,\s*([0-9]+)\s*,\s*[0-9]+\)\s*/>", sheet, text)
    text = re.sub(r"<Highlight>(.*?)</Highlight>", r"\1", text, flags=re.S)
    text = re.sub(r"<Gui\([^>]*\)/>", "", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("ObjectParameter(1)", "冒险者")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def quest_text_files(text_dir):
    """Map quest id -> text CSV, preferring non-test scripts."""
    found = defaultdict(list)
    for path in Path(text_dir).glob("*/*.csv"):
        match = re.search(r"_(\d{5})\.csv$", path.name)
        if not match:
            continue
        quest_id = int(match.group(1)) + 65536
        found[quest_id].append(path)
    result = {}
    for quest_id, paths in found.items():
        paths.sort(key=lambda path: (path.name.startswith("Tst"), path.name))
        result[quest_id] = paths[0]
    return result


def read_steps(path, item_names):
    if path is None:
        return []
    rows = read_csv(path)
    steps = []
    for row in rows[3:]:
        if len(row) < 3:
            continue
        key, text = row[1], row[2]
        if not re.search(r"_SEQ_\d+$", key):
            continue
        text = clean_step(text, item_names)
        if text and text not in ("无", "无。"):
            steps.append(text)
    return steps


def label_map(rows, key_index, value_index):
    result = {}
    for row in rows[3:]:
        if len(row) <= max(key_index, value_index):
            continue
        key = row[key_index].strip()
        if key and key != "0":
            result[key] = row[value_index]
    return result


def build(args):
    quest_rows = read_csv(args.quest_csv)
    header = header_columns(quest_rows)
    missing = [field for field in FIELDS.values() if field not in header]
    if missing:
        raise SystemExit("Quest.csv is missing fields: " + ", ".join(missing))

    columns = {key: header[field] for key, field in FIELDS.items()}
    array_counts = {"previous_quest": 4, "quest_lock": 2, "instance_content": 3,
                    "item_reward": 7, "item_count_reward": 7,
                    "optional_item_reward": 5, "optional_item_count_reward": 5}
    for key, count in array_counts.items():
        for i in range(count):
            name = field_name(ARRAYS[key], i)
            if name not in header:
                raise SystemExit(f"Quest.csv is missing field: {name}")
            columns[name] = header[name]

    data_dir = Path(args.data_dir or Path(args.quest_csv).parent)
    genre_rows = read_csv(data_dir / "JournalGenre.csv")
    category_rows = read_csv(data_dir / "JournalCategory.csv")
    place_rows = read_csv(data_dir / "PlaceName.csv")
    npc_rows = read_csv(data_dir / "ENpcResident.csv")
    beast_rows = read_csv(data_dir / "BeastTribe.csv")
    festival_rows = read_csv(data_dir / "Festival.csv")

    categories = {}
    for row in category_rows[3:]:
        if len(row) >= 5 and row[0] != "0":
            categories[row[0]] = {"name": row[1], "section": row[4]}

    genres = {}
    for row in genre_rows[3:]:
        if len(row) >= 5 and row[0] != "0":
            genres[row[0]] = {"name": row[4], "category": row[2], "icon": row[1]}

    places = label_map(place_rows, 0, 1)
    npcs = label_map(npc_rows, 0, 1)
    beast_tribes = label_map(beast_rows, 0, 11)
    festivals = label_map(festival_rows, 0, 1)

    item_names = {}
    if args.items and Path(args.items).is_file():
        for item in json.loads(Path(args.items).read_text(encoding="utf-8")):
            item_names[str(item["id"])] = item["name"]

    text_files = quest_text_files(args.text_dir)
    quests = []
    used_genres = set()
    used_places = set()
    used_npcs = set()
    text_count = 0
    total_text_bytes = 0

    for row in quest_rows[3:]:
        name = cell(row, columns, "name").strip()
        quest_id = number(row, columns, "id")
        if not name or quest_id == 0:
            continue

        previous = [value for value in array(row, columns, ARRAYS["previous_quest"], 4) if value]
        locks = [value for value in array(row, columns, ARRAYS["quest_lock"], 2) if value]
        genre = number(row, columns, "journal_genre")
        place = number(row, columns, "place_name")
        issuer = number(row, columns, "issuer_start")
        target = number(row, columns, "target_end")
        rewards = {
            "gil": number(row, columns, "gil_reward"),
            "exp": number(row, columns, "exp_factor"),
            "items": [
                [item_id, count]
                for item_id, count in zip(
                    array(row, columns, ARRAYS["item_reward"], 7),
                    array(row, columns, ARRAYS["item_count_reward"], 7),
                )
                if item_id
            ],
            "optional": [
                [item_id, count]
                for item_id, count in zip(
                    array(row, columns, ARRAYS["optional_item_reward"], 5),
                    array(row, columns, ARRAYS["optional_item_count_reward"], 5),
                )
                if item_id
            ],
            "emote": number(row, columns, "emote_reward"),
            "action": number(row, columns, "action_reward"),
            "other": number(row, columns, "other_reward"),
        }
        steps = read_steps(text_files.get(quest_id), item_names)
        if steps:
            text_count += 1
            total_text_bytes += sum(len(step.encode()) for step in steps)

        if genre:
            used_genres.add(str(genre))
        if place:
            used_places.add(str(place))
        for npc in (issuer, target):
            if npc:
                used_npcs.add(str(npc))

        quests.append({
            "id": quest_id,
            "name": name,
            "expansion": number(row, columns, "expansion"),
            "level": number(row, columns, "class_job_level"),
            "level2": number(row, columns, "class_job_level_2"),
            "genre": genre,
            "place": place,
            "sort": number(row, columns, "sort_key"),
            "event": number(row, columns, "event_icon_type"),
            "icon": number(row, columns, "icon"),
            "prev": previous,
            "prevJoin": number(row, columns, "previous_quest_join"),
            "lock": locks,
            "lockJoin": number(row, columns, "quest_lock_join"),
            "issuer": issuer,
            "issuerLocation": number(row, columns, "issuer_location"),
            "target": target,
            "repeatable": truth(row, columns, "is_repeatable"),
            "repeatInterval": number(row, columns, "repeat_interval"),
            "beast": number(row, columns, "beast_tribe"),
            "beastRank": number(row, columns, "beast_rank"),
            "festival": number(row, columns, "festival"),
            "festivalBegin": number(row, columns, "festival_begin"),
            "festivalEnd": number(row, columns, "festival_end"),
            "instance": [value for value in array(row, columns, ARRAYS["instance_content"], 3) if value],
            "classJobRequired": number(row, columns, "class_job_required"),
            "rewards": rewards,
            "steps": steps,
        })

    quests.sort(key=lambda quest: quest["id"])
    if not quests:
        raise SystemExit("No named quests found")
    if len({quest["id"] for quest in quests}) != len(quests):
        raise SystemExit("Duplicate quest ids")

    validate(quests, genres, categories, places)

    snapshot = {
        "version": 1,
        "source": {
            "kind": "datamining",
            "language": "chs",
            "commit": args.commit or "",
            "tailOffset": TAIL_OFFSET,
            "count": len(quests),
            "textCount": text_count,
        },
        "expansions": {str(key): value for key, value in EXPANSIONS.items()},
        "genres": {key: genres[key] for key in sorted(used_genres & set(genres))},
        "places": {key: places[key] for key in sorted(used_places & set(places))},
        "npcs": {key: npcs[key] for key in sorted(used_npcs & set(npcs))},
        "beastTribes": {key: beast_tribes[key] for key in beast_tribes},
        "festivals": {key: festivals[key] for key in festivals},
        "quests": quests,
    }
    # The category set above is easier to express explicitly; keep only used ones.
    used_categories = {genres[str(q["genre"])]["category"] for q in quests if str(q["genre"]) in genres}
    snapshot["categories"] = {key: categories[key] for key in sorted(used_categories) if key in categories}

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"Wrote {len(quests)} quests ({text_count} with steps, {total_text_bytes / 1e6:.2f} MB text) to {output}")
    return snapshot


def validate(quests, genres, categories, places):
    """Cheap invariants that catch a changed CSV layout or offset."""
    by_id = {quest["id"]: quest for quest in quests}
    for quest in quests:
        if quest["genre"] and str(quest["genre"]) not in genres:
            raise SystemExit(f"Unknown JournalGenre {quest['genre']} on quest {quest['id']}")
        if quest["place"] and str(quest["place"]) not in places:
            raise SystemExit(f"Unknown PlaceName {quest['place']} on quest {quest['id']}")
        if quest["sort"] < 0:
            raise SystemExit(f"Invalid SortKey on quest {quest['id']}")
    checks = {
        67140: {"genre": 3, "place": 62, "sort": 25, "gil": 753, "item": 10074},
        70126: {"genre": 244, "place": 53, "sort": 221, "gil": 679, "item": 36857},
    }
    for quest_id, expected in checks.items():
        quest = by_id.get(quest_id)
        if not quest:
            continue
        for key, value in expected.items():
            if key == "item":
                actual = quest["rewards"]["items"][0][0] if quest["rewards"]["items"] else None
            elif key == "gil":
                actual = quest["rewards"]["gil"]
            else:
                actual = quest[key]
            if actual != value:
                raise SystemExit(
                    f"Quest {quest_id} field {key}: expected {value!r}, got {actual!r}. "
                    "The CN Quest.csv layout may have changed."
                )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quest-csv", required=True, type=Path)
    parser.add_argument("--text-dir", required=True, type=Path)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--items", type=Path)
    parser.add_argument("--commit", default="")
    parser.add_argument("--output", type=Path, default=ROOT / "sources/quests.json")
    args = parser.parse_args(argv)
    build(args)


if __name__ == "__main__":
    main()
