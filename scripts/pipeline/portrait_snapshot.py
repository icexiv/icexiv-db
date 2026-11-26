"""Prepare offline portrait previews from reviewed CHS CSVs and client textures."""
import argparse
import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path
import subprocess
import tempfile

if __package__:
    from .unlock_snapshot import sheet
else:
    from unlock_snapshot import sheet

ROOT = Path(__file__).resolve().parents[2]
DECOR = {"1": "背衬", "2": "图案", "3": "肖像外框", "4": "铭牌外框", "5": "装饰物"}


def raw_rows(path):
    # These CHS CSVs have repeated unnamed columns. Keep their column positions.
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.reader(stream)
        next(reader)
        header = next(reader)
        next(reader)
        for values in reader:
            yield header, values


def build(directory, exported, unlock_groups=None):
    raw = exported.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    item_names = {i["id"]: i["name"] for i in json.loads(raw)}
    if unlock_groups is None:
        from scripts.pipeline import bundle
        unlock_groups = bundle.read(bundle.DATAMINING).get("unlocks", {}).get("groups", {})
    ids = set(unlock_groups["肖像教材"])
    actions = {r["#"]: r for r in sheet(directory / "ItemAction.csv")}
    keys = {}
    for r in sheet(directory / "Item.csv"):
        if int(r["#"]) in ids:
            if r["Name"] != item_names[int(r["#"])]:
                raise ValueError(f"Item name mismatch: {r['#']}")
            action = actions[r["ItemAction"]]
            kind, field = {"29459": ("9", r["AdditionalData"]), "2633": ("2", action["Data[0]"])}[action["Type"]]
            if (kind, field) in keys:
                raise ValueError(f"Duplicate kit key {(kind, field)}")
            keys[kind, field] = int(r["#"])
    if set(keys.values()) != ids:
        raise ValueError("Item CSV is missing portrait kits")
    arrays = {v[0]: [i for i in v[1:] if i != "0"]
              for _, v in raw_rows(directory / "GameConditionValueArray.csv")}
    conditions = defaultdict(set)
    for r in sheet(directory / "BannerCondition.csv"):
        kind, key = r["UnlockType1"], r["UnlockCriteria1[0]"]
        candidates = [("9", i) for i in arrays[key]] if kind == "11" else [(kind, key)]
        conditions[r["#"]].update(keys[k] for k in candidates if k in keys)
    names = {r["#"]: r["Name"] for r in sheet(directory / "Action.csv")}
    kits = defaultdict(lambda: defaultdict(list))
    for table, group, kind in [
        ("BannerBg", "肖像", "背景"), ("BannerFrame", "肖像", "装饰框"),
        ("BannerDecoration", "肖像", "装饰物"), ("BannerTimeline", "肖像", "姿势（动作图标）"),
        ("CharaCardBase", "冒险者铭牌", "底色"), ("CharaCardDecoration", "冒险者铭牌", None),
        ("CharaCardHeader", "冒险者铭牌", None),
    ]:
        for header, values in raw_rows(directory / f"{table}.csv"):
            row = dict(zip(header, values))
            start = header.index("UnlockCondition")
            owners = set().union(*(conditions[c] for c in values[start:start + 4] if c != "0"))
            if not owners:
                continue
            label = row["Name"]
            if table == "BannerTimeline":
                label = label or names[row["AdditionalData"]]
                parts = [(kind, row["Icon"])]
            elif table == "CharaCardHeader":
                parts = [(title, row[field]) for title, field in (("上边框", "TopImage"), ("下边框", "BottomImage"))
                         if row[field] != "0"]
            else:
                parts = [(kind or DECOR[row["Category"]], row["Image"])]
            for owner in owners:
                kits[owner][group].extend([title, label, int(image)] for title, image in parts)
    return digest, {i: dict(kits[i]) for i in sorted(ids)}


def main():
    from PIL import Image
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("csv_directory", "items_json", "installation", "exporter"):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    digest, kits = build(args.csv_directory, args.items_json)
    images = sorted({p[2] for groups in kits.values() for rows in groups.values() for p in rows if p[2]})
    destination = ROOT / "game-assets/portraits"
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temp:
        temp = Path(temp)
        ids = temp / "ids.json"
        ids.write_text(json.dumps(images))
        out = temp / "textures"
        subprocess.run([args.exporter, "--portrait-icons", args.installation, ids, out], check=True)
        version = (out / "game-version.txt").read_text()
        for image in images:
            with Image.open(out / f"{image}.png") as texture:
                texture.thumbnail((320, 320), Image.Resampling.LANCZOS)
                texture.save(destination / f"{image}.webp", quality=85)
    from scripts.pipeline import bundle
    bundle.merge(bundle.DATAMINING, {"itemsSha256": digest,
                                     "portraits": {"textureGameVersion": version, "kits": kits}})
    no_image = [(i, title, name) for i, groups in kits.items() for rows in groups.values()
                for title, name, image in rows if not image]
    print(f"{len(images)} textures; unmatched kits: {[i for i, rows in kits.items() if not rows]}; "
          f"parts without image: {no_image}")


if __name__ == "__main__":
    main()
