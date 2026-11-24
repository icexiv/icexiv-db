"""Build the offline first-seen lookup from a full datamining-cn Git checkout."""
import csv
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import sys

HEAD = "3ba064a64e21ff62b587d886701bbe6e74d8d224"
BUILD_PATCH = {
    "2025.12.09": "7.4", "2025.12.18": "7.4", "2025.12.23": "7.4",
    "2026.01.21": "7.41", "2026.02.20": "7.45", "2026.03.07": "7.45",
    "2026.04.21": "7.5", "2026.05.01": "7.5",
}


def build(commits, read_sheet, garland, item_export):
    raw = item_export.read_bytes()
    wanted = {r["id"] for r in json.loads(raw)}
    boundaries = sorted((int(row[4]), row[1]) for row in list(csv.reader(
        io.StringIO(read_sheet(commits[-1][0], "ExVersion"))))[3:] if row[1])
    first_seen = {}
    for i, (sha, message) in enumerate(commits):
        match = re.search(r"\bpatch ([\d.]+)", message)
        build_id = message.split("ver ")[1].split()[0]
        patch = match[1] if match else BUILD_PATCH.get(build_id[:10], f"国服构建 {build_id}")
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
    labels = sorted(set(first_seen.values()))
    ranges = []
    for key, value in sorted(first_seen.items()):
        label = labels.index(value)
        if ranges and ranges[-1][1:] == [key - 1, label]:
            ranges[-1][1] = key
        else:
            ranges.append([key, key, label])
    return {"historyHead": commits[-1][0], "itemsSha256": hashlib.sha256(raw).hexdigest(),
            "labels": labels, "ranges": ranges}


if __name__ == "__main__":
    repo, garland, exported = map(Path, sys.argv[1:])
    def git(*args):
        return subprocess.check_output(["git", "-C", repo, *args]).decode("utf-8-sig")
    commits = [line.split("\t", 1) for line in git("log", HEAD, "--reverse", "--format=%H%x09%s",
                                                  "--", "Item.csv").splitlines()]
    snapshot = build(commits, lambda sha, sheet: git("show", f"{sha}:{sheet}.csv"), garland, exported)
    (Path(__file__).resolve().parents[1] / "sources/releases.json").write_text(
        json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")) + "\n")
