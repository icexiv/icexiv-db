"""Attach the shared base skeleton and idle PAP to existing gear manifests.

The asset paths come from the model's clade. Only the model library's published
manifests are rewritten; objects are read through the renderer probe, which
stores them in the content-addressed directory.
"""
import argparse
import functools
import json
from pathlib import Path
import subprocess

if __package__:
    from .model_library import ANIMATION_RECORD, ROOT, animation_paths, write
else:
    from model_library import ANIMATION_RECORD, ROOT, animation_paths, write

PROBE = ROOT / "target/renderer-probe/release/icexiv-db-renderer-probe"


def main(game, library_path, manifests, objects):
    library = json.loads(library_path.read_bytes())
    hashes = set(library["objects"])
    changed = 0
    with subprocess.Popen([PROBE, game / "game/sqpack", objects],
                          stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True) as proc:
        @functools.cache
        def probe(path):
            print(path, file=proc.stdin, flush=True)
            return json.loads(proc.stdout.readline())

        for item in library["items"]:
            path = manifests / f"{item}.json"
            manifest = json.loads(path.read_bytes())
            animation = animation_paths(manifest["kind"], [p["model"] for p in manifest["parts"]])
            if not animation:
                continue
            resolved = {name: probe(name) for name in animation}
            if not all(r and "sha" in r for r in resolved.values()):
                continue
            update = {name: resolved[name]["sha"] for name in animation}
            record = dict(zip(("sklb", "pap"), animation), record=ANIMATION_RECORD)
            if manifest.get("animation") == record and all(manifest["files"].get(k) == v for k, v in update.items()):
                continue
            manifest["files"].update(update)
            manifest["animation"] = record
            write(path, manifest)
            hashes.update(update.values())
            changed += 1
        proc.stdin.close()
        if proc.wait():
            raise RuntimeError("resource probe failed")
    for digest in hashes:
        if not (objects / digest[:2] / digest[2:]).is_file():
            raise RuntimeError(f"missing model object {digest}")
    library["objects"] = sorted(hashes)
    tmp = library_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(library, separators=(",", ":")) + "\n")
    tmp.replace(library_path)
    print(f"Updated {changed} manifests with {len(hashes)} objects")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("game", type=Path)
    parser.add_argument("--library", type=Path, default=ROOT / "sources/model-library.json")
    parser.add_argument("--manifests", type=Path, default=ROOT / "game-assets/models/manifests")
    parser.add_argument("--objects", type=Path, default=ROOT / "game-assets/models/objects/sha256")
    args = parser.parse_args()
    main(args.game, args.library, args.manifests, args.objects)
