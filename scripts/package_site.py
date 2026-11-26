"""Package one verified Notist build for project Pages and the domestic origin."""

import shutil
import sys
from pathlib import Path

CN_ASSETS = Path(__file__).resolve().parents[1] / "ops/cn"
LEGAL = """<p><a href="https://beian.miit.gov.cn/">京ICP备2026077264号-1</a> ·
<a href="https://beian.mps.gov.cn/#/query/webSearch?code=11010502064164"><img src="/police-beian.png" width="16" height="16" alt=""> 京公网安备11010502064164号</a></p>"""
TRACKER = '<script defer src="/_analytics/tracker.js" referrerpolicy="no-referrer"></script>'


def package(source, pages, domestic):
    # A development media origin would point every visitor at their own machine.
    for sample in (source / "index.html", source / "items/index.html"):
        if sample.is_file() and "http://127.0.0.1:8015/" in sample.read_text(encoding="utf-8"):
            raise ValueError("Local game media cannot be deployed. Build with GAME_ASSETS_SOURCE=disabled or a remote URL.")
    for target in (pages, domestic):
        shutil.copytree(source, target)
    shutil.copytree(CN_ASSETS, domestic, dirs_exist_ok=True)
    for page in domestic.rglob("*.html"):
        rel = page.relative_to(domestic)
        html = page.read_text()
        if html.count("</head>") != 1 or html.count("</footer>") != 1:
            raise ValueError(f"Missing site layout: {rel}")
        page.write_text(html.replace("</head>", TRACKER + "</head>")
                        .replace("</footer>", LEGAL + "</footer>"))


if __name__ == "__main__":
    package(*(Path(arg) for arg in sys.argv[1:]))
