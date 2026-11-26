"""Import and refresh the full 3D model library from a local game install and renderer SDK."""

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.media import EFFECT_SDK, SDK_FILES, file_hash, install_file


def shared_model_groups(manifests):
    groups = {}
    for item, manifest in manifests:
        if manifest.get("kind") not in {"armor", "weapon", "accessory", "facewear"} or manifest.get("incompleteParts"):
            continue
        parts = tuple(part["model"] for part in manifest["parts"])
        if parts:
            groups.setdefault((manifest["kind"], parts), []).append(int(item))
    return sorted(sorted(ids) for ids in groups.values() if len(ids) > 1)


def same_model_groups(source, inventory):
    manifests = ((i, json.loads((source / f"manifests/{i}.json").read_bytes())) for i in inventory["items"])
    return shared_model_groups(manifests)


def import_library(root, source):
    """Install only files referenced by this inventory (not audit reports or stale manifests)."""
    inventory = json.loads((source / "inventory.json").read_text())
    dest = root / "game-assets/models"
    catalog = root / "sources/model-library.json"
    previous = json.loads(catalog.read_text()) if catalog.exists() else {}
    hashes = set()
    has_effects = False
    for i in inventory["items"]:
        if not i.isdecimal():
            raise ValueError(f"Invalid item ID: {i}")
        name = f"manifests/{i}.json"
        manifest = json.loads((source / name).read_bytes())
        hashes.update(manifest["files"].values())
        for part in manifest["parts"]:
            if effect := part.get("effect"):
                has_effects = True
                hashes.update(effect["files"].values())
        install_file(source / name, dest / name)
    for sha in hashes:
        if not re.fullmatch("[a-f0-9]{64}", sha):
            raise ValueError("Invalid object digest")
        key = f"objects/sha256/{sha[:2]}/{sha[2:]}"
        if file_hash(source / key) != sha:
            raise ValueError(f"Corrupt model object {key}")
        install_file(source / key, dest / key)
    for name in SDK_FILES + (EFFECT_SDK if has_effects else ()):
        install_file(source / "sdk" / name, root / "static/model-sdk" / name)
    inventory["objects"] = sorted(hashes)
    # Same-model groups live in the same file so the media manifest is one read.
    inventory["groups"] = same_model_groups(source, inventory)
    tmp = catalog.with_suffix(".tmp")
    tmp.write_text(json.dumps(inventory, separators=(",", ":")) + "\n")
    tmp.replace(catalog)
    # Prune only entries owned by the preceding published inventory, after switching.
    for sha in set(previous.get("objects", [])) - hashes:
        if re.fullmatch("[a-f0-9]{64}", sha):
            (dest / f"objects/sha256/{sha[:2]}/{sha[2:]}").unlink(missing_ok=True)
    for i in previous.get("items", {}).keys() - inventory["items"].keys():
        if i.isdecimal():
            (dest / f"manifests/{i}.json").unlink(missing_ok=True)
    print(f"Installed {len(inventory['items'])} manifests and {len(hashes)} model objects")


def refresh_models(game, sdk):
    from scripts.pipeline.model_audit import audit
    from scripts.pipeline.model_library import build
    from scripts.pipeline.render_failure_report import build as report
    from scripts.pipeline.weapon_effects import attach

    scratch = ROOT / "target"
    scratch.mkdir(exist_ok=True)
    checks = ROOT / "audit/render-check"
    with tempfile.TemporaryDirectory(prefix="model-refresh-", dir=scratch) as tmp:
        stage = Path(tmp)
        audit(game, stage / "model-audit.json")
        build(game, sdk, stage / "library", stage / "model-audit.json")
        for name in EFFECT_SDK:
            install_file(sdk / name, stage / "library/sdk" / name)
        attach(game, stage / "model-audit.json", stage / "library", stage / "weapon-effects.json")
        report(stage)
        import_library(ROOT, stage / "library")
        # Diagnostics can be regenerated from these small files alone.
        for path in [*stage.glob("*.json"), *stage.glob("*.csv"), *stage.glob("library/*.json")]:
            install_file(path, checks / path.relative_to(stage))
    # Use the caller's site Python (includes Pillow), in the ordinary local environment.
    subprocess.run([sys.executable, ROOT / "scripts/items.py", "prepare"], check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(required=True, dest="command")
    commands.add_parser("import-models").add_argument("library", type=Path)
    refresh = commands.add_parser("refresh-models")
    refresh.add_argument("game", type=Path)
    refresh.add_argument("sdk", type=Path)
    args = parser.parse_args()
    if args.command == "refresh-models":
        refresh_models(args.game, args.sdk)
    else:
        import_library(ROOT, args.library)


if __name__ == "__main__":
    main()
