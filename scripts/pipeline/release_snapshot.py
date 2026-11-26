"""Build the offline first-seen lookup from a full datamining-cn Git checkout."""
import csv
import io
import json
from pathlib import Path
import re
import subprocess
import sys

HEAD = "3ba064a64e21ff62b587d886701bbe6e74d8d224"
SOURCES = Path(__file__).resolve().parents[2] / "sources"


def build_patches():
    entries = json.loads((SOURCES / "build-patches.json").read_text())
    for key, entry in entries.items():
        if not (re.fullmatch(r"\d{4}\.\d{2}\.\d{2}\.\d{4}\.\d{4}", key)
                and re.fullmatch(r"\d+\.\d+", entry["patch"])
                and entry["source"].startswith("https://")):
            raise ValueError(f"Invalid build-patches.json entry: {key}")
    return {key: entry["patch"] for key, entry in entries.items()}


def build(commits, read_sheet, garland, item_export):
    wanted = {r["id"] for r in json.loads(item_export.read_bytes())}
    boundaries = sorted((int(row[4]), row[1]) for row in list(csv.reader(
        io.StringIO(read_sheet(commits[-1][0], "ExVersion"))))[3:] if row[1])
    first_seen = {}
    history_order = []
    patches = build_patches()
    missing = set()
    for i, (sha, message) in enumerate(commits):
        match = re.search(r"\bpatch ([\d.]+)", message)
        build_id = message.split("ver ")[1].split()[0]
        patch = match[1] if match else patches.get(build_id)
        if patch is None:
            missing.add(build_id)
            patch = f"国服构建 {build_id}"
        if patch not in history_order:
            history_order.append(patch)
        reader = csv.reader(io.StringIO(read_sheet(sha, "Item"), newline=""))
        next(reader)
        name = next(reader).index("Name")
        next(reader)
        for row in reader:
            item = int(row[0])
            if item not in wanted or item in first_seen or not row[name].strip():
                continue
            if i:
                first_seen[item] = patch
            else:
                expansion = next((v for k, v in reversed(boundaries) if k <= item), "")
                first_seen[item] = {"重生之境": "2.x", "苍穹之禁城": "3.x"}.get(expansion, f"{patch} 及以前")
    for row in json.loads(garland.read_text(encoding="utf-8-sig")):
        if row["type"] == "item" and row["patch"] < 4.45 and int(row["id"]) in wanted:
            first_seen[int(row["id"])] = "1.x（具体版本未知）" if row["patch"] < 2 else str(float(row["patch"]))
    # The baseline is only bounded by its expansion or by the first snapshot.
    # Later builds belong at their historical position even without a patch number.
    seen_labels = set(first_seen.values())
    labels = sorted(seen_labels - set(history_order), key=lambda p: (float(re.match(r"\d+(?:\.\d+)?", p)[0]), p))
    labels.extend(p for p in history_order if p in seen_labels)
    ranges = []
    for key, value in sorted(first_seen.items()):
        label = labels.index(value)
        if ranges and ranges[-1][1:] == [key - 1, label]:
            ranges[-1][1] = key
        else:
            ranges.append([key, key, label])
    if missing:
        print("缺少补丁映射（保留国服构建号）：" + "、".join(sorted(missing)), file=sys.stderr)
    return {"historyHead": commits[-1][0], "labels": labels, "ranges": ranges}


if __name__ == "__main__":
    repo, garland, exported = map(Path, sys.argv[1:])
    def git(*args):
        return subprocess.check_output(["git", "-C", repo, *args]).decode("utf-8-sig")
    commits = [line.split("\t", 1) for line in git("log", HEAD, "--reverse", "--format=%H%x09%s",
                                                  "--", "Item.csv").splitlines()]
    snapshot = build(commits, lambda sha, sheet: git("show", f"{sha}:{sheet}.csv"), garland, exported)
    from scripts.pipeline import bundle
    bundle.merge(bundle.REFERENCE, {"releases": snapshot})
