"""Export emote previews: a shared dressed actor, a hidden weapon host and one
action bundle per mapped item.

Requires the renderer checkout's native exporters and a local game install.
Objects go to the shared content-addressed directory; manifests become
`game-assets/models/actions/<item>.json` and are listed in
`sources/action-library.json`.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
OBJECTS = ROOT / "game-assets/models/objects/sha256"
MANIFESTS = ROOT / "game-assets/models/actions"
HIDDEN_HOST = (1 << 32) | (62 << 16) | 101  # w0101b0062, variant 1
# Race IDs follow the customize byte; tribe is the first of each race.
RACES = [
    (1, "人族", 1, (0, 1)),
    (2, "精灵族", 3, (0, 1)),
    (3, "拉拉菲尔族", 5, (0, 1)),
    (4, "猫魅族", 7, (0, 1)),
    (5, "鲁加族", 9, (0, 1)),
    (6, "敖龙族", 11, (0, 1)),
    (7, "硌狮族", 13, (0,)),
]
DEFAULT = (6, 1)
# CharaMakeType defaults per race/gender (datamining-cn), with race, sex and
# tribe bytes restored. Face, hair and palette bytes follow the game defaults.
CUSTOMIZE = {
    "1-0": [1, 0, 1, 50, 1, 4, 51, 0, 3, 30, 103, 0, 0, 0, 1, 0, 4, 5, 2, 0, 35, 50, 0, 0, 0, 0],
    "1-1": [1, 1, 1, 50, 1, 0, 6, 0, 1, 37, 54, 0, 0, 2, 0, 0, 0, 0, 0, 0, 44, 50, 0, 50, 0, 0],
    "2-0": [2, 0, 1, 50, 3, 1, 26, 0, 82, 28, 52, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 25, 2, 0, 0, 0],
    "2-1": [2, 1, 1, 50, 3, 3, 18, 0, 82, 53, 43, 0, 0, 0, 0, 0, 0, 0, 0, 0, 39, 25, 0, 50, 0, 0],
    "3-0": [3, 0, 1, 50, 5, 0, 18, 0, 25, 11, 29, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 25, 1, 0, 0, 0],
    "3-1": [3, 1, 1, 50, 5, 0, 21, 0, 25, 11, 182, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 25, 1, 25, 0, 0],
    "4-0": [4, 0, 1, 50, 7, 0, 9, 0, 146, 22, 94, 0, 0, 7, 0, 0, 0, 0, 0, 0, 0, 25, 0, 0, 0, 0],
    "4-1": [4, 1, 1, 50, 7, 2, 3, 0, 136, 81, 92, 0, 0, 0, 0, 0, 0, 0, 1, 1, 42, 25, 0, 50, 0, 0],
    "5-0": [5, 0, 1, 50, 9, 1, 5, 0, 25, 13, 165, 0, 0, 6, 0, 0, 0, 0, 0, 0, 0, 25, 0, 0, 0, 0],
    "5-1": [5, 1, 1, 50, 9, 3, 28, 0, 42, 47, 177, 0, 0, 0, 0, 0, 0, 0, 0, 3, 44, 25, 0, 50, 0, 0],
    "6-0": [6, 0, 1, 50, 11, 1, 2, 0, 109, 150, 183, 0, 0, 138, 0, 0, 0, 0, 0, 0, 0, 50, 0, 0, 0, 0],
    "6-1": [6, 1, 1, 50, 11, 1, 0, 0, 16, 90, 90, 0, 0, 36, 0, 1, 4, 0, 1, 0, 43, 50, 0, 50, 0, 0],
    "7-0": [7, 0, 1, 50, 13, 1, 5, 0, 27, 43, 46, 0, 0, 7, 3, 0, 2, 2, 2, 2, 0, 50, 0, 0, 0, 0],
}
EQUIPMENT = []  # The body carries the racial default clothing.
IDLE = "chara/human/c0101/animation/a0001/bt_common/resident/idle.pap"
PREVIEW = {"units_per_second": 30, "bindings": [], "enabled_tracks": []}


def run(command, stdin=None):
    result = subprocess.run(command, input=stdin, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"{command[0]}: {result.stderr.strip() or result.stdout.strip()}")
    return result.stdout


def collect(manifest):
    return {sha for sha in manifest.get("files", {}).values()}


def actor_bundle(renderer, game, race, gender, tribe):
    base = CUSTOMIZE[f"{race}-{gender}"]
    request = ROOT / f"target/action-actor-{race}-{gender}.json"
    export = str(renderer / "effects/target/release/examples/export_actor")
    args = [export, str(game / "game"), str(OBJECTS)]
    candidates = [base] + [
        base[:5] + [face, hair] + base[7:]
        for hair in (0, 1, 2) for face in (0, 1, 2, 3)
    ]
    probe = None
    for customize in candidates:
        request.write_text(json.dumps({"customize": customize, "equipment": EQUIPMENT,
                                       "pap": IDLE, "record": 1}))
        try:
            probe = json.loads(run(args + [str(request)]))
            break
        except RuntimeError:
            continue
    if probe is None:
        raise RuntimeError(f"no valid actor appearance for race {race} gender {gender}")
    clade = probe["sklb"].split("/")[2]
    request.write_text(json.dumps({"customize": customize, "equipment": EQUIPMENT,
                                   "pap": f"chara/human/{clade}/animation/a0001/bt_common/resident/idle.pap",
                                   "record": 1}))
    try:
        return json.loads(run(args + [str(request)]))
    except RuntimeError:
        # Some clades ship no resident idle PAP; the shared c0101 clip decodes
        # with the same bone names and only drops tracks the skeleton lacks.
        return probe


def host_bundle(renderer, game):
    export = renderer / "effects/target/release/examples/export"
    return json.loads(run([str(export), str(game / "game"), str(OBJECTS), "--owner"],
                          stdin=f"{HIDDEN_HOST}\n"))


def pick_timelines(timelines):
    """Select full-body start/loop/end sequence, skipping upper-body (u_*) and additive (add_*)."""
    full = []
    for row, key in timelines:
        leaf = key.rsplit("/", 1)[-1]
        if leaf.startswith(("u_", "add_")):
            continue
        full.append((row, key, leaf))
    if not full:
        return [timelines[0][0]]
    # Prefer explicit start -> loop -> end ordering if present.
    starts = [r for r, k, _ in full if k.endswith("_start")]
    loops = [r for r, k, _ in full if k.endswith("_loop")]
    ends = [r for r, k, _ in full if k.endswith("_end")]
    seq = []
    if starts:
        seq.append(starts[0])
    if loops:
        seq.append(loops[0])
    if ends:
        seq.append(ends[0])
    if seq:
        return seq
    return [full[0][0]]


def preview_for(bundle):
    seen_targets = set()
    bindings = []
    # Prefer full VFX tracks ([13, 0, 0]) over party/simplified tracks ([12, 0, 0]).
    has_full = any(
        [13, 0, 0] in (link.get("conditions") or [])
        for eff in bundle.get("effects", [])
        for link in eff.get("chain", [])
    )
    enabled_tracks = []
    seen_tracks = set()
    for eff in bundle.get("effects", []):
        for target in eff.get("targets", []):
            key = (target["origin"], target["kind"], target["id"])
            if key not in seen_targets:
                seen_targets.add(key)
                bindings.append({"target": target, "position": [0, 0, 0]})
        chain = eff.get("chain", [])
        is_simplified = any(
            [12, 0, 0] in (link.get("conditions") or [])
            for link in chain
        )
        if has_full and is_simplified:
            continue
        for link in chain:
            if link.get("conditions"):
                tk = (link["tmb"], link["track"])
                if tk not in seen_tracks:
                    seen_tracks.add(tk)
                    enabled_tracks.append([tk[0], tk[1]])
    return {
        "units_per_second": 30,
        "bindings": bindings,
        "enabled_tracks": enabled_tracks,
    }


def main(game, renderer, limit=None, actors_only=False):
    from scripts.pipeline import bundle
    actions = bundle.read(bundle.DATAMINING).get("actions", {})
    if not actions:
        raise ValueError("Run scripts/pipeline/manifest.py from-csv first (missing datamining.actions)")
    MANIFESTS.mkdir(parents=True, exist_ok=True)
    actors = {}
    objects = set()
    actors_dir = MANIFESTS / "actors"
    actors_dir.mkdir(exist_ok=True)
    for race, label, tribe, genders in RACES:
        for gender in genders:
            actor = actor_bundle(renderer, game, race, gender, tribe)
            name = f"{race}-{gender}"
            path = actors_dir / f"{name}.json"
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(actor, separators=(",", ":")))
            tmp.replace(path)
            actors[name] = f"models/actions/actors/{name}.json"
            objects |= collect(actor)
    previous = (ROOT / "sources/action-library.json")
    prev_data = json.loads(previous.read_bytes()) if previous.is_file() else {}
    items = prev_data.get("items", {}) if actors_only else {}
    items_sha = actions.get("itemsSha256") or prev_data.get("itemsSha256") or hashlib.sha256(
        json.dumps(actions["items"], sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    library = {"itemsSha256": items_sha, "items": items, "actors": actors,
               "races": [{"id": race, "label": label, "genders": list(genders)} for race, label, _, genders in RACES],
               "default": list(DEFAULT)}
    tool = renderer / "effects/tools/target/release/icexiv-action"
    written = 0
    for item, entry in ({} if actors_only else actions["items"]).items():
        timelines = entry["timelines"]
        seq_ids = pick_timelines(timelines)
        bundle = json.loads(run([str(tool), "--pack", str(game / "game/sqpack"),
                                 "--timelines", ",".join(str(x) for x in seq_ids),
                                 str(OBJECTS), "--actor", "101"]))
        if bundle["unresolvedClips"] or not bundle["clips"]:
            continue
        objects |= collect(bundle)
        manifest = dict(objects="../objects/sha256/", bundle=bundle, preview=preview_for(bundle))
        path = MANIFESTS / f"{item}.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(manifest, separators=(",", ":")))
        tmp.replace(path)
        library["items"][item] = f"models/actions/{item}.json"
        written += 1
        if limit and written >= limit:
            break
    for sha in objects:
        if not (OBJECTS / sha[:2] / sha[2:]).is_file():
            raise RuntimeError(f"missing object {sha}")
    library["objects"] = sorted(objects)
    tmp = (ROOT / "sources/action-library.json").with_suffix(".tmp")
    tmp.write_text(json.dumps(library, separators=(",", ":")) + "\n")
    tmp.replace(ROOT / "sources/action-library.json")
    print(f"Wrote {written} action manifests with {len(objects)} objects")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("game", type=Path)
    parser.add_argument("renderer", type=Path)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--actors-only", action="store_true")
    args = parser.parse_args()
    main(args.game, args.renderer, args.limit, args.actors_only)
