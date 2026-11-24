"""Package one verified Notist build for project Pages and the domestic origin."""

import re
import shutil
import sys
from pathlib import Path

CN_ASSETS = Path(__file__).resolve().parents[1] / "ops/cn"
LEGAL = """<p><a href="https://beian.miit.gov.cn/">京ICP备2026077264号-1</a> ·
<a href="https://beian.mps.gov.cn/#/query/webSearch?code=11010502064164"><img src="/police-beian.png" width="16" height="16" alt=""> 京公网安备11010502064164号</a></p>"""
TRACKER = '<script defer src="/_analytics/tracker.js" referrerpolicy="no-referrer"></script>'
ROOT_URL = re.compile(r'(\s(?:href|src|action)=")/(?!/)')


def package(source, pages, domestic):
    for target in (pages, domestic):
        shutil.copytree(source, target)
    shutil.copytree(CN_ASSETS, domestic, dirs_exist_ok=True)
    for page in pages.rglob("*.html"):
        rel = page.relative_to(pages)
        html = page.read_text()
        if html.count("</head>") != 1 or html.count("</footer>") != 1:
            raise ValueError(f"Missing site layout: {rel}")
        (domestic / rel).write_text(html.replace("</head>", TRACKER + "</head>")
                                   .replace("</footer>", LEGAL + "</footer>"))
        prefix = "../" * len(rel.parent.parts) or "./"
        page.write_text(ROOT_URL.sub(lambda m: m[1] + prefix, html))


if __name__ == "__main__":
    package(*(Path(arg) for arg in sys.argv[1:]))
