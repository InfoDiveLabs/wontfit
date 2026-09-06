"""``phoneframes shoot``: PNG screenshots via Playwright, which is optional.

Playwright is imported lazily and guarded so the core package stays
dependency-free. Screenshots go straight to the upstream (no proxy needed:
a headless browser is not bothered by ``X-Frame-Options``).
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

INSTALL_HINT = (
    "phoneframes shoot needs Playwright, which is optional:\n"
    "    pip install 'phoneframes[shoot]'   # or: pip install playwright\n"
    "    playwright install chromium\n"
)


def slug_for(page: str) -> str:
    """``/`` -> ``index``; ``/about/team?x=1`` -> ``about-team``."""
    path = page.split("?", 1)[0].split("#", 1)[0].strip("/")
    cleaned = re.sub(r"[^A-Za-z0-9]+", "-", path).strip("-").lower()
    return cleaned or "index"


def planned_files(pages: list[str], widths: list[int], height: int, landscape: bool, out: Path) -> list[Path]:
    """The files ``shoot`` will write, in order (kept pure so it can be tested)."""
    files = []
    for page in pages:
        for width in widths:
            w, h = (height, width) if landscape else (width, height)
            files.append(out / f"{slug_for(page)}-{w}x{h}.png")
    return files


def shoot(ns: argparse.Namespace) -> int:
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError:
        sys.stderr.write(INSTALL_HINT)
        return 2

    out = Path(ns.out)
    out.mkdir(parents=True, exist_ok=True)
    targets = list(
        zip(
            [(p, w) for p in ns.pages for w in ns.widths],
            planned_files(ns.pages, ns.widths, ns.height, ns.landscape, out),
        )
    )
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            for (page_path, width), file in targets:
                w, h = (ns.height, width) if ns.landscape else (width, ns.height)
                context = browser.new_context(
                    viewport={"width": w, "height": h},
                    device_scale_factor=2,
                    ignore_https_errors=ns.insecure,
                    extra_http_headers=dict(ns.header),
                )
                if ns.cookie:
                    context.add_cookies(
                        [{"name": k, "value": v, "url": ns.upstream + "/"} for k, v in ns.cookie]
                    )
                page = context.new_page()
                page.goto(ns.upstream + page_path, wait_until="networkidle")
                page.screenshot(path=str(file), full_page=ns.full_page)
                context.close()
                print(f"wrote {file}")
            browser.close()
    except PlaywrightError as exc:
        sys.stderr.write(f"phoneframes shoot: {exc}\n")
        if "Executable doesn't exist" in str(exc) or "playwright install" in str(exc):
            sys.stderr.write("Run: playwright install chromium\n")
        return 1
    return 0
