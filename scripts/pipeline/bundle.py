"""Read and merge the committed data bundles under ``sources/``.

``datamining.json`` holds everything derived from one datamining CSV batch;
``reference.json`` holds external lookup tables keyed by stable item ids.
Each snapshot script merges only its own key, so they stay independent.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCES = ROOT / "sources"
DATAMINING = SOURCES / "datamining.json"
REFERENCE = SOURCES / "reference.json"


def read(path):
    path = Path(path)
    return json.loads(path.read_bytes()) if path.is_file() else {}


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")


def merge(path, values):
    data = read(path)
    data.update(values)
    write(path, data)
    return data


def facet(result):
    """Drop a per-facet itemsSha256; the bundle records the batch once."""
    return {key: value for key, value in result.items() if key != "itemsSha256"}
