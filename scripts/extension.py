"""Notist site extension protocol handlers (before_compile and before_template).

Reads pure manifest output from ``content/.data/`` and supplies the game-assets
resolver configuration at ``notist serve`` / ``notist build`` time via ``scripts/media.py``.
"""

import hashlib
import json

if __package__:
    from .export_loader import ITEM_CHUNK, ROOT, prepared_catalog
    from .media import Media
else:
    from export_loader import ITEM_CHUNK, ROOT, prepared_catalog
    from media import Media


def _read_source(root, rel_path):
    path = root / rel_path
    return json.loads(path.read_bytes()) if path.is_file() else {}


def _build_runtime_assets(root):
    media = Media(root)
    bases = dict(media.bases)
    if not media.enabled:
        return bases, None

    site_assets = dict(bases)
    if bases.get("models"):
        actions = _read_source(root, "sources/action-library.json")
        if actions and actions.get("actors"):
            site_assets["actionActors"] = dict(actions["actors"])
            site_assets["actionDefault"] = "-".join(map(str, actions["default"]))
    return bases, site_assets


def _asset_rev(root):
    digest = hashlib.sha256()
    static = root / "static"
    if static.is_dir():
        for path in sorted(static.iterdir()):
            if path.is_file() and path.suffix in {".css", ".js"}:
                digest.update(path.name.encode("utf-8"))
                digest.update(b"\0")
                digest.update(path.read_bytes())
                digest.update(b"\0")
    return digest.hexdigest()[:10]


def extend(request, input_path, limit=None, *, state=None, root=ROOT):
    if request.get("version") != 2:
        raise ValueError("Unsupported Notist site extension protocol")
    event = request.get("event")
    if event == "before_template":
        if state is None or "catalog" not in state:
            raise ValueError("before_compile must succeed before before_template")
        data = dict(request["data"])
        data["catalog"] = state["catalog"]
        data["asset_rev"] = _asset_rev(root)
        if state.get("assets"):
            data["assets"] = state["assets"]
        return {"version": 2, "event": event, "data": data}

    if event != "before_compile":
        raise ValueError("Unsupported Notist site extension event")
    if state is not None:
        state.clear()

    item_ids, catalog = prepared_catalog(root=root)
    if limit is not None:
        item_ids = item_ids[:limit]

    runtime_cfg, site_assets = _build_runtime_assets(root)
    data_files = {
        ".data/runtime-assets.json": json.dumps(runtime_cfg, ensure_ascii=False, separators=(",", ":")),
    }

    documents = dict(request["documents"])

    def add_document(path, template, call):
        if path in documents:
            raise ValueError(f"Generated page conflicts with handwritten content: {path}")
        prefix = "../" * (path.count("/") + 1)
        documents[path] = f'@!(template: "{template}")\n#import "{prefix}modules/views.not" as views;\n{call}\n'

    for position, item_id in enumerate(item_ids):
        path = f"items/{item_id}.md"
        chunk, index = divmod(position, ITEM_CHUNK)
        up = "../" * path.count("/")
        add_document(path, "item", f'#views.item("{up}.data/items/{chunk}.json", {index})')

    page_count = catalog["pageCount"]
    for page in range(1, page_count + 1):
        path = "items/index.md" if page == 1 else f"items/page/{page}.md"
        up = "../" * path.count("/")
        add_document(path, "catalog", f'#views.catalog("{up}.data/catalog/page-{page}.json")')

    if state is not None:
        state["catalog"] = catalog
        if site_assets:
            state["assets"] = site_assets
    return {"version": 2, "event": event, "documents": documents, "data_files": data_files}


def write_response(response, stream):
    stream.write(json.dumps(response, ensure_ascii=False, separators=(",", ":")))
    stream.write("\n")
    stream.flush()
