"""Inventory publication files by logical path, without writing to any input directory."""
import csv
import gzip
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "audit/deployment-inventory"


def inventory():
    OUT.mkdir(parents=True, exist_ok=True)
    groups = {}
    objects = set(json.loads((ROOT / "sources/model-library.json").read_bytes())["objects"])
    action_lib = ROOT / "sources/action-library.json"
    if action_lib.is_file():
        objects.update(json.loads(action_lib.read_bytes()).get("objects", []))
    customize_lib = ROOT / "sources/customize-library.json"
    if customize_lib.is_file():
        objects.update(json.loads(customize_lib.read_bytes()).get("objects", []))
    chocobo = ROOT / "game-assets/models/actions/actors/chocobo.json"
    if chocobo.is_file():
        objects.update(json.loads(chocobo.read_bytes()).get("files", {}).values())
    origins = {
        "game-assets": "CDN", "static": "Notist 静态输入", "ops/cn": "国内包附加",
        "assets": "设计源文件",
        "notist-output/icexiv-db": "当前站点输出",
    }
    with gzip.open(OUT / "files.csv.gz", "wt", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["用途", "相对仓库路径", "字节", "SHA-256"])
        for name, role in origins.items():
            base = ROOT / name
            for p in sorted(base.rglob("*")):
                if not p.is_file():
                    continue
                rel = p.relative_to(base)
                group = rel.parts[0] if len(rel.parts) > 1 else "(root)"
                label = role
                if name == "game-assets" and group == "models":
                    group += "/" + rel.parts[1]
                    if group == "models/objects" and p.parent.name + p.name not in objects:
                        label = "本地对象，当前模型库存未引用"
                size = p.stat().st_size
                with p.open("rb") as f:
                    sha = hashlib.file_digest(f, "sha256").hexdigest()
                writer.writerow([label, p.relative_to(ROOT), size, sha])
                key = f"{name}/{group}"
                totals = groups.setdefault(key, {"files": 0, "bytes": 0})
                totals["files"] += 1
                totals["bytes"] += size
    (OUT / "groups.json").write_text(json.dumps(groups, indent=2, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    inventory()
