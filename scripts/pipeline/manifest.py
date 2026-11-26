"""Build the site data manifest and every CSV-derived facet in one batch.

This is the CI path: no game installation, no ``game-export`` archive. It writes
``items.json``/``manifest.json`` for the site, and one ``sources/datamining.json``
bundle holding all tabular facets for that same batch.

Usage:
    python3 scripts/pipeline/manifest.py from-csv CSV_DIR [--output inputs/game-export]

Optional tables (Recipe, OrchestrionPath, Emote, ActionTimeline, Banner*, …) are
used when present and skipped with a note when absent.
"""

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.pipeline import bundle  # noqa: E402
from scripts.pipeline import (  # noqa: E402
    action_snapshot, equipment_snapshot, orchestrion, portrait_snapshot,
    recipe_book_snapshot, unlock_snapshot,
)
from scripts.pipeline.unlock_snapshot import sheet  # noqa: E402

REQUIRED = ("Item.csv",)
EQUIPMENT = ("Item.csv", "ClassJob.csv", "ClassJobCategory.csv", "EquipSlotCategory.csv")
PORTRAITS = ("BannerCondition.csv", "GameConditionValueArray.csv", "Action.csv", "BannerBg.csv",
             "BannerFrame.csv", "BannerDecoration.csv", "BannerTimeline.csv",
             "CharaCardBase.csv", "CharaCardDecoration.csv", "CharaCardHeader.csv")


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def file_digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _number(row, name):
    value = row.get(name, "")
    return int(value) if value not in ("", None) else 0


def _flag(row, name):
    return row.get(name, "") == "True"


def read_items(csv_directory):
    records = []
    for row in sheet(csv_directory / "Item.csv"):
        key = row.get("#", "")
        if not key or key == "0" or not row.get("Name", "").strip():
            continue
        records.append({
            "id": int(key),
            "name": row["Name"],
            "description": row.get("Description", ""),
            "icon": _number(row, "Icon"),
            "category": _number(row, "ItemUICategory"),
            "searchCategory": _number(row, "ItemSearchCategory"),
            "equipLevel": _number(row, "Level{Equip}"),
            "rarity": _number(row, "Rarity"),
            "stackSize": _number(row, "StackSize"),
            "unique": _flag(row, "IsUnique"),
            "untradable": _flag(row, "IsUntradable"),
            "hq": _flag(row, "CanBeHq"),
        })
    if not records:
        raise ValueError("Item.csv contained no named rows")
    if len({record["id"] for record in records}) != len(records):
        raise ValueError("Item.csv contains duplicate ids")
    records.sort(key=lambda record: record["id"])
    return records


def build_manifest(csv_directory, output, *, game_version=None, commit=None, snapshots=True):
    csv_directory = Path(csv_directory)
    output = Path(output)
    missing = [name for name in REQUIRED if not (csv_directory / name).is_file()]
    if missing:
        raise SystemExit(f"missing required CSV: {', '.join(missing)}")
    records = read_items(csv_directory)
    output.mkdir(parents=True, exist_ok=True)

    item_bytes = json.dumps(records, ensure_ascii=False, separators=(",", ":")).encode()
    (output / "items.json").write_bytes(item_bytes)
    used = sorted(path for path in csv_directory.iterdir() if path.suffix == ".csv")
    source = {
        "kind": "datamining",
        "gameVersion": game_version or f"datamining-cn@{commit[:7] if commit else 'unknown'}",
        "language": "chs",
        "commit": commit or "",
        "files": {path.name: file_digest(path) for path in used},
    }
    manifest = {
        "version": 2,
        "source": source,
        "itemsSha256": digest(item_bytes),
        "itemCount": len(records),
    }
    (output / "manifest.json").write_bytes(
        json.dumps(manifest, ensure_ascii=False, separators=(",", ":")).encode())
    print(f"Wrote {len(records)} item records to {output}")

    if snapshots:
        write_snapshots(csv_directory, output, source=source)


def write_snapshots(csv_directory, output, *, source):
    """Rebuild every facet from this CSV batch into sources/datamining.json."""
    exported = output / "items.json"
    item_csv, action_csv = csv_directory / "Item.csv", csv_directory / "ItemAction.csv"
    items_sha = hashlib.sha256(exported.read_bytes()).hexdigest()
    facets = {}

    def emit(key, value, note=""):
        facets[key] = bundle.facet(value)
        print(f"datamining.{key}: {note}".rstrip(": "))

    if all((csv_directory / name).is_file() for name in EQUIPMENT):
        emit("equipment", equipment_snapshot.build(csv_directory, exported))
    else:
        print("skip equipment (missing ClassJob/EquipSlotCategory tables)")

    if not action_csv.is_file():
        print("skip unlocks/recipes/orchestrion/actions (missing ItemAction.csv)")
        bundle.write(bundle.DATAMINING, {"itemsSha256": items_sha, "source": source, **facets})
        return

    unlocks = unlock_snapshot.build(item_csv, action_csv, exported)
    emit("unlocks", unlocks)

    if (csv_directory / "Recipe.csv").is_file():
        emit("recipes", recipe_book_snapshot.build(
            item_csv, action_csv, csv_directory / "Recipe.csv", exported))
    else:
        print("skip recipes (missing Recipe.csv)")

    if (csv_directory / "OrchestrionPath.csv").is_file():
        emit("orchestrion", orchestrion.snapshot(
            item_csv, action_csv, csv_directory / "OrchestrionPath.csv", exported))
    else:
        print("skip orchestrion (missing OrchestrionPath.csv)")

    if (csv_directory / "Emote.csv").is_file() and (csv_directory / "ActionTimeline.csv").is_file():
        emit("actions", action_snapshot.build(
            item_csv, action_csv, csv_directory / "Emote.csv",
            csv_directory / "ActionTimeline.csv", exported))
    else:
        print("skip actions (missing Emote/ActionTimeline tables)")

    if all((csv_directory / name).is_file() for name in PORTRAITS):
        _, kits = portrait_snapshot.build(csv_directory, exported, unlocks["groups"])
        texture = bundle.read(bundle.DATAMINING).get("portraits", {}).get("textureGameVersion", "")
        emit("portraits", {"kits": kits, "textureGameVersion": texture}, f"{len(kits)} kits")
    else:
        print("skip portraits (missing banner tables)")

    bundle.write(bundle.DATAMINING, {"itemsSha256": items_sha, "source": source, **facets})


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("from-csv", help="build items.json/manifest.json and the datamining bundle")
    build.add_argument("csv_directory", type=Path)
    build.add_argument("--output", type=Path, default=ROOT / "inputs/game-export")
    build.add_argument("--game-version")
    build.add_argument("--commit")
    build.add_argument("--items-only", action="store_true", help="skip the source bundle")
    args = parser.parse_args()
    build_manifest(args.csv_directory, args.output, game_version=args.game_version,
                   commit=args.commit, snapshots=not args.items_only)


if __name__ == "__main__":
    main()
