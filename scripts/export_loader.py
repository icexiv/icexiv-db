"""Validate a site data manifest and build shared catalog metadata.

The primary input is a datamining CSV manifest produced by
``scripts/pipeline/manifest.py from-csv`` (version 2). Legacy version 1
``items.json`` exports are still accepted for item rows, but icons and other
binary media are always resolved independently through ``scripts/media.py``.

Nothing here reads a game installation, PNG icons, a CSV, or the network.
"""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGE_SIZE = 100
ITEM_CHUNK = 1000
RECIPE_SHARD = 128
RELATIONS_PER_SHARD = 16
PLACEHOLDER = "/icon-placeholder.svg"
NUMBERS = ["id", "icon", "category", "searchCategory", "equipLevel", "rarity", "stackSize"]
BOOLEANS = ["unique", "untradable", "hq"]
CATEGORIES = json.loads(Path(__file__).with_name("categories.json").read_text(encoding="utf-8"))
# Every snapshot that changes the generated asset path either way.
SNAPSHOT_FILES = (
    "sources/datamining.json",
    "sources/reference.json",
    "sources/model-library.json",
    "sources/action-library.json",
)


def category_name(item):
    return CATEGORIES.get(str(item["category"]), [f"类型 #{item['category']}"])[0]


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def file_sha256(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def parse_items(raw):
    records = json.loads(raw)
    if not isinstance(records, list) or not records:
        raise ValueError("Expected nonempty exported Item array")
    seen = set()
    for item in records:
        if not isinstance(item, dict):
            raise ValueError("Expected exported Item object")
        for key in NUMBERS:
            value = item.get(key)
            if type(value) is not int or not 0 <= value <= 0xffffffff:
                raise ValueError(f"Invalid Item integer: {key}")
        for key in BOOLEANS:
            if type(item.get(key)) is not bool:
                raise ValueError(f"Invalid Item boolean: {key}")
        for key in ["name", "description"]:
            if not isinstance(item.get(key), str):
                raise ValueError(f"Invalid Item text: {key}")
        if item["id"] == 0 or not item["name"].strip():
            raise ValueError("Export must contain named, nonzero Item rows only")
        if item["id"] in seen:
            raise ValueError(f"Duplicate item ID: {item['id']}")
        seen.add(item["id"])
    return sorted(records, key=lambda item: item["id"])


def _check_source(export, root):
    source = export.get("source", {})
    version = export.get("version")
    if version == 2:
        if source.get("kind") != "datamining" or not source.get("gameVersion") or not source.get("commit"):
            raise ValueError("Datamining manifest is missing its source identity")
        if not source.get("files"):
            raise ValueError("Datamining manifest is missing its input digests")
    elif version == 1:
        schema_bytes = (root / "sources/item-schema.json").read_bytes()
        schema = json.loads(schema_bytes)
        if (source.get("kind") != "game" or source.get("gameVersion") != schema["gameVersion"]
                or source.get("language") != schema["language"]
                or source.get("schemaSha256") != sha256(schema_bytes)
                or source.get("resources", {}).get("exd/item.exh") != schema["exhSha256"]):
            raise ValueError("Game export does not match the reviewed Item schema")
    else:
        raise ValueError("Unsupported site data manifest version")


def load_export(directory, *, root=ROOT):
    """Return (manifest, records, manifest digest)."""
    manifest_bytes = (directory / "manifest.json").read_bytes()
    export = json.loads(manifest_bytes)
    _check_source(export, root)
    item_bytes = (directory / "items.json").read_bytes()
    if sha256(item_bytes) != export.get("itemsSha256"):
        raise ValueError("Exported items.json SHA-256 mismatch")
    records = parse_items(item_bytes)
    if len(records) != export.get("itemCount"):
        raise ValueError("Exported Item count mismatch")
    return export, records, sha256(manifest_bytes)


def pagination_links(page, total):
    start = max(1, min(page - 2, total - 4))
    visible = sorted({1, total, *range(start, min(start + 5, total + 1))})
    links = []
    for i, n in enumerate(visible):
        if i and n - visible[i - 1] > 2:
            links.append(["…", ""])
        elif i and n - visible[i - 1] == 2:
            links.append([str(n - 1), f"/items/page/{n - 1}.html"])
        path = "/items/index.html" if n == 1 else f"/items/page/{n}.html"
        links.append([str(n), "" if n == page else path])
    return links


def catalog_pages(items, source):
    page_count = max(1, (len(items) + PAGE_SIZE - 1) // PAGE_SIZE)
    return [{
        "count": len(items), "version": source["gameVersion"], "pageSize": PAGE_SIZE,
        "label": f"第 {page} / {page_count} 页",
        "pagination": pagination_links(page, page_count),
        "previous": ("/items/index.html" if page == 2 else
                     f"/items/page/{page - 1}.html" if page > 2 else ""),
        "next": f"/items/page/{page + 1}.html" if page < page_count else "",
        "items": [[str(item["id"]), item["name"], category_name(item), str(item["icon"])]
                  for item in items[(page - 1) * PAGE_SIZE:page * PAGE_SIZE]],
    } for page in range(1, page_count + 1)]


def catalog_metadata(export, digest, count, *, root=ROOT):
    payload = b"item-facets-relations-v2\0" + digest.encode() + json.dumps(CATEGORIES).encode()
    for rel in SNAPSHOT_FILES:
        path = root / rel
        if path.exists():
            payload += path.read_bytes()
    return {
        "source": export["source"], "exportSha256": digest, "count": count,
        "pageSize": PAGE_SIZE, "pageCount": max(1, (count + PAGE_SIZE - 1) // PAGE_SIZE),
        "assetPath": f"generated/{sha256(payload)[:16]}",
    }


def prepared_catalog(*, root=ROOT):
    """Build-time view of ``prepare`` output; reads nothing outside content/.data."""
    private = root / "content/.data"
    catalog_path, receipt_path = private / "catalog.json", private / "prepared.json"
    if not (catalog_path.is_file() and receipt_path.is_file()):
        raise ValueError("Run scripts/items.py prepare before building the site")
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt.get("assetPath") != catalog.get("assetPath"):
        raise ValueError("Run scripts/items.py prepare before building the site")
    return catalog.pop("items"), catalog
