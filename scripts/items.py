"""Validate an offline game export and prepare Notist inputs; no network or game IO."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parent.parent
PAGE_SIZE = 100
ITEM_CHUNK = 1000
PLACEHOLDER = "/icon-placeholder.svg"
NUMBERS = ["id", "icon", "category", "searchCategory", "equipLevel", "rarity", "stackSize"]
BOOLEANS = ["unique", "untradable", "hq"]


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


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


def load_export(directory, verify_icons=True):
    raw = (directory / "manifest.json").read_bytes()
    export = json.loads(raw)
    schema_bytes = (ROOT / "sources/item-schema.json").read_bytes()
    schema = json.loads(schema_bytes)
    source = export.get("source", {})
    if (export.get("version") != 1 or source.get("kind") != "game"
            or source.get("gameVersion") != schema["gameVersion"]
            or source.get("language") != schema["language"]
            or source.get("schemaSha256") != sha256(schema_bytes)
            or source.get("resources", {}).get("exd/item.exh") != schema["exhSha256"]):
        raise ValueError("Game export does not match the reviewed Item schema")
    item_bytes = (directory / "items.json").read_bytes()
    if sha256(item_bytes) != export.get("itemsSha256"):
        raise ValueError("Exported items.json SHA-256 mismatch")
    records = parse_items(item_bytes)
    if len(records) != export.get("itemCount"):
        raise ValueError("Exported Item count mismatch")
    required = {str(item["icon"]) for item in records}
    if set(export.get("icons", {})) != required:
        raise ValueError("Incomplete or unexpected icon ID set")
    assets = {}
    for key in sorted(required, key=int):
        entry = export["icons"][key]
        status = entry.get("status")
        if key == "0" and status == "unconfigured":
            continue
        if key != "0" and status == "missing":
            continue
        if status != "exported" or key == "0":
            raise ValueError(f"Icon {key}: incomplete or failed export")
        if not verify_icons:
            continue
        png = (directory / "icons" / f"{key}.png").read_bytes()
        if sha256(png) != entry.get("sha256"):
            raise ValueError(f"Icon {key}: PNG SHA-256 mismatch")
        if (png[:8] != b"\x89PNG\r\n\x1a\n" or len(png) < 33 or png[12:16] != b"IHDR"
                or type(entry.get("width")) is not int or type(entry.get("height")) is not int
                or not 0 < entry["width"] <= 65535 or not 0 < entry["height"] <= 65535
                or int.from_bytes(png[16:20], "big") != entry["width"]
                or int.from_bytes(png[20:24], "big") != entry["height"]):
            raise ValueError(f"Icon {key}: invalid PNG metadata")
        assets[int(key)] = png
    return export, records, assets, sha256(raw)


def item_record(item):
    return [
        str(item["id"]), item["name"], item["description"], str(item["category"]),
        str(item["searchCategory"]), str(item["equipLevel"]), str(item["rarity"]),
        str(item["stackSize"]), "是" if item["unique"] else "否",
        "是" if item["untradable"] else "否", "是" if item["hq"] else "否",
        str(item["icon"]), item.get("iconUrl", PLACEHOLDER),
    ]


def catalog_pages(items, source):
    page_count = max(1, (len(items) + PAGE_SIZE - 1) // PAGE_SIZE)
    return [{
        "count": len(items), "version": source["gameVersion"], "pageSize": PAGE_SIZE,
        "label": f"第 {page} / {page_count} 页",
        "previous": ("/items/index.html" if page == 2 else
                     f"/items/page/{page - 1}.html" if page > 2 else ""),
        "next": f"/items/page/{page + 1}.html" if page < page_count else "",
        "items": [[str(item["id"]), item["name"], str(item["category"]), item.get("iconUrl", PLACEHOLDER)]
                  for item in items[(page - 1) * PAGE_SIZE:page * PAGE_SIZE]],
    } for page in range(1, page_count + 1)]


def catalog_metadata(export, digest, count):
    return {
        "source": export["source"], "exportSha256": digest, "count": count,
        "pageSize": PAGE_SIZE, "pageCount": max(1, (count + PAGE_SIZE - 1) // PAGE_SIZE),
        "assetPath": f"generated/{digest[:16]}",
    }


def prepared_catalog(input_path):
    export, records, _, digest = load_export(input_path, verify_icons=False)
    receipt = ROOT / "content/.data/prepared.json"
    if not receipt.is_file() or json.loads(receipt.read_text(encoding="utf-8")) != {"exportSha256": digest}:
        raise ValueError("Run scripts/items.py prepare before building the site")
    return records, catalog_metadata(export, digest, len(records))


def prepare(input_path):
    export, records, icons, digest = load_export(input_path)
    (ROOT / "content/.data/prepared.json").unlink(missing_ok=True)
    asset_path = f"generated/{digest[:16]}"
    for item in records:
        item["iconUrl"] = (f"/{asset_path}/icons/{item['icon']}.png" if item["icon"] in icons else PLACEHOLDER)
    # These two namespaces belong exclusively to this preparation script.
    generated = ROOT / "static/generated"
    if generated.exists():
        shutil.rmtree(generated)
    assets = ROOT / "static" / asset_path
    if icons:
        (assets / "icons").mkdir(parents=True, exist_ok=True)
        for icon_id, png in icons.items():
            (assets / "icons" / f"{icon_id}.png").write_bytes(png)
    write_json(assets / "index.json", [[i["id"], i["name"], i["category"], i["iconUrl"]] for i in records])
    pages = catalog_pages(records, export["source"])
    private = ROOT / "content/.data"
    shutil.rmtree(private, ignore_errors=True)
    for chunk, start in enumerate(range(0, len(records), ITEM_CHUNK)):
        write_json(private / "items" / f"{chunk}.json", [item_record(item) for item in records[start:start + ITEM_CHUNK]])
    for page, record in enumerate(pages, 1):
        write_json(private / "catalog" / f"page-{page}.json", record)
    # Publish the receipt last: incomplete preparation must not be used by a build.
    write_json(private / "prepared.json", {"exportSha256": digest})
    print(f"Prepared {len(records)} item records and {len(pages)} catalog pages")


def extend(request, input_path, limit=None, *, state=None):
    if request.get("version") != 2:
        raise ValueError("Unsupported Notist site extension protocol")
    event = request.get("event")
    if event == "before_template":
        if state is None or "catalog" not in state:
            raise ValueError("before_compile must succeed before before_template")
        data = dict(request["data"])
        data["catalog"] = state["catalog"]
        return {"version": 2, "event": event, "data": data}
    if event != "before_compile":
        raise ValueError("Unsupported Notist site extension event")
    if state is not None:
        state.clear()
    records, catalog = prepared_catalog(input_path)
    if limit is not None:
        records = records[:limit]
    documents = dict(request["documents"])

    def add_document(path, call):
        if path in documents:
            raise ValueError(f"Generated page conflicts with handwritten content: {path}")
        prefix = "../" * (path.count("/") + 1)
        documents[path] = f'#import "{prefix}modules/views.notc" as views;\n{call}\n'

    for position, item in enumerate(records):
        path = f"items/{item['id']}.not"
        chunk, index = divmod(position, ITEM_CHUNK)
        add_document(path, f'#views.item(p"{"../" * path.count("/")}.data/items/{chunk}.json", {index})')
    page_count = max(1, (len(records) + PAGE_SIZE - 1) // PAGE_SIZE)
    for page in range(1, page_count + 1):
        path = "items/index.not" if page == 1 else f"items/page/{page}.not"
        add_document(path, f'#views.catalog(p"{"../" * path.count("/")}.data/catalog/page-{page}.json")')
    if state is not None:
        state["catalog"] = catalog
    return {"version": 2, "event": event, "documents": documents}


def write_response(response, stream):
    stream.write(json.dumps(response, ensure_ascii=False, separators=(",", ":")))
    stream.write("\n")
    stream.flush()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "extension"])
    parser.add_argument("--input", type=Path, default=ROOT / "inputs/game-export")
    parser.add_argument("--limit", type=int, help="Limit generated pages for profiling only")
    args = parser.parse_args()
    if args.action == "extension":
        state = {}
        for line in sys.stdin:
            request = {}
            try:
                request = json.loads(line)
                response = extend(request, args.input, args.limit, state=state)
            except Exception as error:
                state.clear()
                response = {"version": 2, "event": request.get("event"), "errors": [str(error)]}
            write_response(response, sys.stdout)
    else:
        prepare(args.input)


if __name__ == "__main__":
    main()
