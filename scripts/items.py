"""CLI entrypoint: prepare pure manifest data and run the Notist site extension."""

import argparse
import json
import sys
from pathlib import Path

if __package__:
    from . import export_loader as _loader
    from . import extension as _extension
    from . import prepare as _prepare
else:
    import export_loader as _loader
    import extension as _extension
    import prepare as _prepare

ROOT = _loader.ROOT
PLACEHOLDER = _loader.PLACEHOLDER
write_json = _loader.write_json
sha256 = _loader.sha256
parse_items = _loader.parse_items
catalog_pages = _loader.catalog_pages
category_name = _loader.category_name
write_response = _extension.write_response


def load_export(directory):
    return _loader.load_export(directory, root=ROOT)


def catalog_metadata(export, digest, count):
    return _loader.catalog_metadata(export, digest, count, root=ROOT)


def prepared_catalog():
    return _loader.prepared_catalog(root=ROOT)


def prepare(input_path):
    return _prepare.prepare(input_path, root=ROOT, emit_json=write_json)


def extend(request, input_path, limit=None, *, state=None):
    return _extension.extend(request, input_path, limit, state=state, root=ROOT)


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
