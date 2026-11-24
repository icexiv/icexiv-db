"""Build the unlock facet from CHS Item.csv, ItemAction.csv and exported items.json."""
import csv
import hashlib
import json
from pathlib import Path
import sys


# Display order and candidate rules from xiv-companion's collection classification.
ACTIONS = {
    "坐骑": 1322, "宠物": 853, "乐谱": 25183, "情感动作": None, "发型与面妆": None,
    "时尚配饰": 20086, "面部配饰": 37312, "生产秘籍": 2136, "传习录": 4107,
    "详细地图": None, "肖像教材": 29459, "鸟甲": 1013, "九宫幻卡": 3357,
    "方城声援": None, "其他解锁": None,
}
BY_ACTION = {action: label for label, action in ACTIONS.items() if action}


def classify(name, action, category):
    if action in BY_ACTION:
        return BY_ACTION[action]
    if action == 2633:
        for prefix, label in [("演技教材", "情感动作"), ("发型样式", "发型与面妆"),
                              ("面妆样式", "发型与面妆"), ("方城金句集", "方城声援"), ("肖像教材", "肖像教材")]:
            if name.startswith(prefix):
                return label
        if name.endswith("详细地图"):
            return "详细地图"
    if category in (81, 94):
        return "宠物" if category == 81 else "乐谱"
    if action in (2633, 18083, 19743, 43141, 43142):
        return "其他解锁"


def sheet(path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = csv.reader(f)
        next(rows)
        header = next(rows)
        next(rows)
        for row in rows:
            yield dict(zip(header, row))


def build(items_csv, actions_csv, exported):
    raw = exported.read_bytes()
    items = {i["id"]: i for i in json.loads(raw)}
    actions = {r["#"]: int(r["Type"]) for r in sheet(actions_csv)}
    groups = {label: [] for label in ACTIONS}
    for row in sheet(items_csv):
        if not row["Name"] or row["#"] == "0":
            continue
        item = items.pop(int(row["#"]))
        if (row["Name"], int(row["ItemUICategory"])) != (item["name"], item["category"]):
            raise ValueError(f"Item mismatch: {item['id']}")
        if not int(row["EquipSlotCategory"]):
            kind = classify(item["name"], actions[row["ItemAction"]], item["category"])
            if kind:
                groups[kind].append(item["id"])
    if items:
        raise ValueError("Item CSV incomplete")
    return dict(itemsSha256=hashlib.sha256(raw).hexdigest(), groups=groups)


if __name__ == "__main__":
    result = build(*map(Path, sys.argv[1:]))
    (Path(__file__).resolve().parents[1] / "sources/unlocks.json").write_text(
        json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n")
