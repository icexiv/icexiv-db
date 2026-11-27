"""Verify the generated catalog, data shards and all static links without a server."""

from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys
from urllib.parse import unquote, urlsplit

from items import prepared_catalog, prepared_quests

ROOT = Path(__file__).resolve().parent.parent
RECIPE_SHARD = 128
RELATION_SHARD = 16


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attributes):
        for key, value in attributes:
            if key in {"href", "src"} and value:
                self.links.append(value)


def main():
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "notist-output/icexiv-db"
    _, catalog = prepared_catalog()
    assets = output / catalog["assetPath"]
    index = json.loads((assets / "index.json").read_text())
    assert len(index) == catalog["count"]
    expected = {f"{item[0]}.html" for item in index}
    actual = {p.name for p in (output / "items").glob("*.html") if p.name != "index.html"}
    assert actual == expected, "Missing or stale item detail pages"
    expected_pages = (len(index) + catalog["pageSize"] - 1) // catalog["pageSize"]
    assert 1 + len(list((output / "items/page").glob("*.html"))) == expected_pages
    failures = []
    for record in index:
        icon = record[3]
        assert isinstance(icon, int) and icon >= 0, f"Expected integer icon ID, got {icon!r}"
    # Every detail page references only shards that were actually generated.
    for page in (output / "items").glob("*.html"):
        if page.name == "index.html":
            continue
        html = page.read_text()
        for shard in {int(n) for n in re.findall(r'<notist-modules-game-recipe-panel\b[^>]*notist-id="(\d+)"', html)}:
            if not (assets / "recipes" / f"{shard // RECIPE_SHARD}.json").is_file():
                failures.append(f"{page}: missing recipe shard for item {shard}")
        for key in {int(n) for n in re.findall(r'<notist-modules-game-gear-group\b[^>]*notist-key="(\d+)"', html)}:
            if not (assets / "relations" / f"{key // RELATION_SHARD}.json").is_file():
                failures.append(f"{page}: missing relation shard for group {key}")
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
    assert 'id="item-fields"' in sample and "首次收录版本" in sample, "Item details must render without JavaScript"

    quests = prepared_quests()
    if quests:
        expected_quests = {f"{quest_id}.html" for quest_id in quests["items"]}
        actual_quests = {p.name for p in (output / "quests").glob("*.html") if p.name != "index.html"}
        assert actual_quests == expected_quests, "Missing or stale quest detail pages"
        expected_quest_pages = (quests["count"] + quests["pageSize"] - 1) // quests["pageSize"]
        assert 1 + len(list((output / "quests/page").glob("*.html"))) == expected_quest_pages
        expected_series = {f"{slug}.html" for slug, _name, _total in quests["series"]}
        actual_series = {p.name for p in (output / "quests/series").glob("*.html")}
        assert actual_series == expected_series, "Missing or stale quest series pages"
        quest_sample = (output / "quests/67118.html").read_text()
        assert "notist-modules-quests-graph" in quest_sample and "quest-graph-fallback" in quest_sample
        assert "任务流程" in quest_sample and "云雾缭绕" in quest_sample
        print(f"Verified {len(quests['items'])} quest detail pages, {expected_quest_pages} quest catalog pages, "
              f"{len(expected_series)} quest series pages")
    print(f"Verified {len(index)} static item pages, {expected_pages} catalog pages and all local HTML links")


if __name__ == "__main__":
    main()
