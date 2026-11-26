"""Map playable CHS rolls to SqPack tracks and export complete MP3s for the CDN."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.pipeline import bundle
if __package__:
    from .unlock_snapshot import sheet
else:
    from unlock_snapshot import sheet


def snapshot(items, actions, paths, exported):
    action = {r["#"]: r["Type"] for r in sheet(actions)}
    files = {r["#"]: r["File"] for r in sheet(paths)}
    raw = exported.read_bytes()
    names = {i["id"]: i["name"] for i in json.loads(raw)}
    tracks = {}
    for row in sheet(items):
        if not row["Name"] or action[row["ItemAction"]] != "25183":
            continue
        item = int(row["#"])
        if names.get(item) != row["Name"]:
            raise ValueError(f"Item mismatch: {item}")
        path = files[row["AdditionalData"]]
        if not path.endswith(".scd"):
            raise ValueError(f"No SCD for item {item}")
        tracks[item] = path
    return {"itemsSha256": sha256(raw).hexdigest(), "tracks": tracks}


def export(args):
    tracks = bundle.read(args.snapshot).get("orchestrion", {}).get("tracks", {})
    args.output.mkdir(parents=True, exist_ok=True)

    def convert(entry):
        item, path = entry
        dest = args.output / f"{int(item)}.mp3"
        with tempfile.TemporaryDirectory(dir=args.output) as directory:
            scd, wav, mp3 = (Path(directory) / f"track.{ext}" for ext in ("scd", "wav", "mp3"))
            for command in ([args.extractor, args.sqpack, path, scd],
                            ["vgmstream-cli", "-i", "-o", wav, scd],
                            ["ffmpeg", "-v", "error", "-i", wav, "-c:a", "libmp3lame", "-q:a", "4", mp3]):
                subprocess.run(command, check=True, stdout=subprocess.DEVNULL)
            mp3.replace(dest)

    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        list(pool.map(convert, tracks.items()))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("snapshot")
    for field in ("items", "actions", "paths", "exported"):
        build.add_argument(field, type=Path)
    audio = commands.add_parser("export")
    for field in ("sqpack", "extractor", "output"):
        audio.add_argument(field, type=Path)
    audio.add_argument("--snapshot", type=Path, default=bundle.DATAMINING,
                       help="bundle holding orchestrion.tracks")
    audio.add_argument("--jobs", type=int, default=4)
    args = parser.parse_args()
    if args.command == "snapshot":
        result = snapshot(args.items, args.actions, args.paths, args.exported)
        bundle.merge(bundle.DATAMINING, {"itemsSha256": result["itemsSha256"],
                                         "orchestrion": bundle.facet(result)})
    else:
        export(args)
