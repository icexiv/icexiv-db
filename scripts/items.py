"""Pinned CSV input and deterministic, offline site data preparation."""

import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
import shutil
import sys
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
PAGE_SIZE = 100
REQUIRED = [
    "#", "Name", "Description", "Icon", "ItemUICategory", "ItemSearchCategory",
    "Level{Equip}", "Rarity", "StackSize", "IsUnique", "IsUntradable", "CanBeHq",
]


def manifest():
    return json.loads((ROOT / "sources/item.json").read_text())


def source_url(source):
    return (f"https://raw.githubusercontent.com/{source['repository']}/"
            f"{source['commit']}/{source['path']}")


def verify(raw, source):
    if hashlib.sha256(raw).hexdigest() != source["sha256"]:
        raise ValueError("Item.csv SHA-256 mismatch; do not use an unpinned input")


def parse_items(raw):
    rows = csv.reader(io.StringIO(raw.decode("utf-8-sig"), newline=""))
    numbers = next(rows, [])
    headers = next(rows, [])
    types = next(rows, [])
    if not numbers or numbers[0] != "key" or not types or types[0] != "int32":
        raise ValueError("Expected master branch's three-row CSV header")
    for key in REQUIRED:
        if headers.count(key) != 1:
            raise ValueError(f"Missing or duplicate CSV field: {key}")
    columns = {key: headers.index(key) for key in REQUIRED}
    items, seen = [], set()
    for line, row in enumerate(rows, 4):
        if len(row) != len(headers):
            raise ValueError(f"Row {line}: wrong column count")
        fields = {key: row[index] for key, index in columns.items()}
        item_id = int(fields["#"])
        if item_id in seen:
            raise ValueError(f"Duplicate item ID: {item_id}")
        seen.add(item_id)
        if item_id == 0 or not fields["Name"].strip():
            continue
        item = {
            "id": item_id,
            "path": f"items/{item_id}.html",
            "name": fields["Name"],
            "description": fields["Description"],
        }
        for field, key in [
            ("Icon", "icon"), ("ItemUICategory", "category"),
            ("ItemSearchCategory", "searchCategory"), ("Level{Equip}", "equipLevel"),
            ("Rarity", "rarity"), ("StackSize", "stackSize"),
        ]:
            item[key] = int(fields[field])
        if not 0 <= item["icon"] <= 0xffffffff:
            raise ValueError(f"Invalid Icon ID in item {item_id}")
        for field, key in [
            ("IsUnique", "unique"), ("IsUntradable", "untradable"), ("CanBeHq", "hq"),
        ]:
            value = fields[field].lower()
            if value not in {"true", "false", "0", "1"}:
                raise ValueError(f"Invalid boolean {field} in item {item_id}")
            item[key] = value in {"true", "1"}
        items.append(item)
    return sorted(items, key=lambda item: item["id"])


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")


PLACEHOLDER = "/icon-placeholder.svg"


def icon_request(input_path, output_path):
    source = manifest()
    raw = input_path.read_bytes()
    verify(raw, source)
    records = parse_items(raw)
    write_json(output_path, {
        "version": 1, "gameVersion": source["gameVersion"],
        "csvSha256": source["sha256"],
        "iconIds": sorted({item["icon"] for item in records}),
    })


def load_icons(directory, source, records):
    """Validate a complete export before touching generated site data."""
    if directory is None:
        return {}, ""
    raw = (directory / "manifest.json").read_bytes()
    export = json.loads(raw)
    if (export.get("version") != 1 or export.get("gameVersion") != source["gameVersion"]
            or export.get("csvSha256") != source["sha256"]):
        raise ValueError("Icon export does not match the pinned Item source")
    assets = {}
    for icon_id in sorted({item["icon"] for item in records}):
        entry = export.get("icons", {}).get(str(icon_id), {})
        status = entry.get("status")
        if icon_id == 0 and status == "unconfigured":
            continue
        if status == "missing":
            if icon_id == 0:
                raise ValueError("Icon 0 must be unconfigured")
            continue
        if status != "exported" or icon_id == 0:
            raise ValueError(f"Icon {icon_id}: incomplete or failed export")
        # Filenames are derived from validated IDs, never supplied by a manifest.
        png = (directory / f"{icon_id}.png").read_bytes()
        if hashlib.sha256(png).hexdigest() != entry.get("sha256"):
            raise ValueError(f"Icon {icon_id}: PNG SHA-256 mismatch")
        if (png[:8] != b"\x89PNG\r\n\x1a\n" or len(png) < 33
                or png[12:16] != b"IHDR"
                or int.from_bytes(png[16:20], "big") != entry.get("width")
                or int.from_bytes(png[20:24], "big") != entry.get("height")
                or not 0 < entry["width"] <= 65535 or not 0 < entry["height"] <= 65535):
            raise ValueError(f"Icon {icon_id}: invalid PNG metadata")
        assets[icon_id] = png
    return assets, hashlib.sha256(raw).hexdigest()[:16]


ITEM_CHUNK = 1000


def item_record(item):
    """Schema-stable display fields consumed by modules/views.notc."""
    return [
        str(item["id"]), item["name"], item["description"], str(item["category"]),
        str(item["searchCategory"]), str(item["equipLevel"]), str(item["rarity"]),
        str(item["stackSize"]), "是" if item["unique"] else "否",
        "是" if item["untradable"] else "否", "是" if item["hq"] else "否",
        str(item["icon"]), item.get("iconUrl", PLACEHOLDER),
    ]


def catalog_pages(items, source):
    page_count = max(1, (len(items) + PAGE_SIZE - 1) // PAGE_SIZE)
    pages = []
    for page in range(1, page_count + 1):
        pages.append({
            "count": len(items), "version": source["gameVersion"],
            "pageSize": PAGE_SIZE, "sourceUrl": source_url(source),
            "label": f"第 {page} / {page_count} 页",
            "previous": ("/items/index.html" if page == 2 else
                         f"/items/page/{page - 1}.html" if page > 2 else ""),
            "next": f"/items/page/{page + 1}.html" if page < page_count else "",
            "items": [
                [str(item["id"]), item["name"], str(item["category"]), item.get("iconUrl", PLACEHOLDER)]
                for item in items[(page - 1) * PAGE_SIZE:page * PAGE_SIZE]
            ],
        })
    return pages


def prepare(input_path, icons=None):
    source = manifest()
    raw = input_path.read_bytes()
    verify(raw, source)
    items = parse_items(raw)
    if not items:
        raise ValueError("No named items found")
    icon_assets, icon_hash = load_icons(icons, source, items)
    asset_path = f"generated/{source['sha256'][:16]}" + (f"-{icon_hash}" if icon_hash else "")
    for item in items:
        item["iconUrl"] = (f"/{asset_path}/icons/{item['icon']}.png"
                           if item["icon"] in icon_assets else PLACEHOLDER)
    # These locations are exclusively generated by this script.
    generated = ROOT / "static/generated"
    if generated.exists():
        shutil.rmtree(generated)
    assets = ROOT / "static" / asset_path
    if icon_assets:
        (assets / "icons").mkdir(parents=True, exist_ok=True)
        for icon_id, png in icon_assets.items():
            (assets / "icons" / f"{icon_id}.png").write_bytes(png)
    write_json(assets / "index.json", [[i["id"], i["name"], i["category"], i["iconUrl"]] for i in items])
    page_count = max(1, (len(items) + PAGE_SIZE - 1) // PAGE_SIZE)
    write_json(ROOT / "data/catalog.json", {
        "source": source, "sourceUrl": source_url(source), "count": len(items),
        "pageSize": PAGE_SIZE, "pageCount": page_count, "assetPath": asset_path,
    })
    # Split inputs so each notc read stays below the data parser working-set
    # limit. Items keep their sorted position; generated pages pass the chunk
    # path and index directly. Rebuild both generated namespaces from scratch.
    private = ROOT / "content/.data"
    shutil.rmtree(private, ignore_errors=True)
    item_data = private / "items"
    catalog_data = private / "catalog"
    for old in (ROOT / "data/items.json", ROOT / "data/catalog-pages.json",
                ROOT / "data/items", ROOT / "data/catalog"):
        if old.is_dir():
            shutil.rmtree(old)
        else:
            old.unlink(missing_ok=True)
    for chunk, start in enumerate(range(0, len(items), ITEM_CHUNK)):
        write_json(item_data / f"{chunk}.json",
                   [item_record(item) for item in items[start:start + ITEM_CHUNK]])
    for page, record in enumerate(catalog_pages(items, source), 1):
        write_json(catalog_data / f"page-{page}.json", record)
    print(f"Prepared {len(items)} item records and {page_count} catalog pages")


def extend(request, input_path, limit=None):
    if request.get("version") != 1 or request.get("stage") != "prepare":
        raise ValueError("Unsupported Notist site extension protocol")
    source = manifest()
    raw = input_path.read_bytes()
    verify(raw, source)
    items = parse_items(raw)
    if limit is not None:
        items = items[:limit]
    site = request["input"]
    documents = site["documents"]
    catalog = site["data"].get("catalog")
    if not catalog or catalog["source"] != source or "pageCount" not in catalog:
        raise ValueError("Run scripts/items.py prepare before building the site")

    def prefix(path):
        # Generated pages keep content/ as their logical root. The project
        # modules/ and data/ directories are one level above content/.
        return "../" * (path.count("/") + 1)

    def add_document(path, call):
        if path in documents:
            raise ValueError(f"Generated page conflicts with handwritten content: {path}")
        documents[path] = (
            f'#import "{prefix(path)}modules/views.notc" as views;\n'
            f"{call}\n"
        )

    for position, item in enumerate(items):
        path = f"items/{item['id']}.not"
        chunk, index = divmod(position, ITEM_CHUNK)
        add_document(
            path,
            f'#views.item(p"{"../" * path.count("/")}.data/items/{chunk}.json", {index})',
        )
    page_count = max(1, (len(items) + PAGE_SIZE - 1) // PAGE_SIZE)
    for page in range(1, page_count + 1):
        path = "items/index.not" if page == 1 else f"items/page/{page}.not"
        add_document(
            path,
            f'#views.catalog(p"{"../" * path.count("/")}.data/catalog/page-{page}.json")',
        )
    return {"version": 1, "input": site}


def write_response(response, stream):
    # Encode in one batch: json.dump otherwise walks the response through
    # millions of Python generator steps before writing its small fragments.
    stream.write(json.dumps(response, ensure_ascii=False, separators=(",", ":")))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["fetch", "prepare", "extension", "icons-request"])
    parser.add_argument("--input", type=Path, default=ROOT / "inputs/Item.csv")
    parser.add_argument("--limit", type=int, help="Limit generated items for profiling only")
    parser.add_argument("--icons", type=Path, help="Verified icon-export output directory (prepare)")
    parser.add_argument("--output", type=Path, default=ROOT / "inputs/icons-request.json")
    args = parser.parse_args()
    if args.action == "extension":
        try:
            response = extend(json.load(sys.stdin), args.input, args.limit)
        except Exception as error:
            response = {"version": 1, "errors": [str(error)]}
        write_response(response, sys.stdout)
    elif args.action == "icons-request":
        icon_request(args.input, args.output)
    elif args.action == "fetch":
        source = manifest()
        with urllib.request.urlopen(source_url(source), timeout=120) as response:
            raw = response.read()
        verify(raw, source)
        # Validate before replacing the previous input.
        parse_items(raw)
        args.input.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.input.with_suffix(".csv.tmp")
        temporary.write_bytes(raw)
        temporary.replace(args.input)
        print(f"Downloaded and verified {args.input} ({len(raw)} bytes)")
    else:
        prepare(args.input, args.icons)


if __name__ == "__main__":
    main()
