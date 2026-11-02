"""Verify the real generated catalog and all its static links without a server."""

from html.parser import HTMLParser
import json
from pathlib import Path
import sys
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parent.parent


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attributes):
        for key, value in attributes:
            if key in {"href", "src"} and value:
                self.links.append(value)


def main():
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "dist/icexiv-db"
    catalog = json.loads((ROOT / "data/catalog.json").read_text())
    index = json.loads((output / catalog["assetPath"] / "index.json").read_text())
    assert len(index) == catalog["count"]
    expected = {f"{item[0]}.html" for item in index}
    actual = {p.name for p in (output / "items").glob("*.html") if p.name != "index.html"}
    assert actual == expected, "Missing or stale item detail pages"
    expected_pages = (len(index) + catalog["pageSize"] - 1) // catalog["pageSize"]
    assert 1 + len(list((output / "items/page").glob("*.html"))) == expected_pages
    failures = []
    for path in output.rglob("*.html"):
        parser = Links()
        parser.feed(path.read_text())
        for link in parser.links:
            parsed = urlsplit(link)
            if parsed.scheme or parsed.netloc or not parsed.path:
                continue
            target = (output if parsed.path.startswith("/") else path.parent) / unquote(parsed.path.lstrip("/"))
            if not target.exists():
                failures.append(f"{path}: {link}")
    assert not failures, "Broken local links:\n" + "\n".join(failures[:20])
    sample = (output / "items/1.html").read_text()
    assert "金币" in sample and "艾欧泽亚" in sample
    assert '<script type="module"' not in sample, "Item details must not require JavaScript"
    print(f"Verified {len(index)} static item pages, {expected_pages} catalog pages and all local HTML links")


if __name__ == "__main__":
    main()
