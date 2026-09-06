"""``wontfit shoot``: a PNG per page x width plus a tiled contact sheet.

Needs Playwright (optional, see :mod:`wontfit._browser`). Screenshots go
straight to the upstream; a headless browser is not bothered by
``X-Frame-Options``. The contact sheet is rendered by the same browser from a
generated HTML page, so no image library is required.
"""

from __future__ import annotations

import argparse
import base64
import html
import re
import sys
from pathlib import Path

SHEET_NAME = "contact-sheet.png"
SHEET_GAP = 24
SHEET_PAD = 28
MAX_SHEET_COLUMNS = 4


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


def sheet_columns(width_count: int) -> int:
    """One column per width, wrapping after :data:`MAX_SHEET_COLUMNS`."""
    return max(1, min(width_count, MAX_SHEET_COLUMNS))


def sheet_viewport_width(widths: list[int], columns: int) -> int:
    """CSS width of the sheet page: the widest possible row plus gaps and padding."""
    row = sorted(widths, reverse=True)[:columns]
    return sum(row) + SHEET_GAP * (len(row) - 1) + SHEET_PAD * 2


def contact_sheet_html(entries: list[tuple[str, int, int, bytes]], columns: int, title: str) -> str:
    """HTML for the sheet. ``entries`` are ``(page, width, height, png_bytes)``."""
    cells = []
    for page, width, height, png in entries:
        src = "data:image/png;base64," + base64.b64encode(png).decode("ascii")
        cells.append(
            f'<figure style="width:{width}px"><img src="{src}" width="{width}" alt="">'
            f"<figcaption><b>{html.escape(page)}</b> {width}x{height}</figcaption></figure>"
        )
    return (
        "<!doctype html><meta charset=utf-8><title>wontfit contact sheet</title>"
        "<style>"
        f"body{{margin:0;padding:{SHEET_PAD}px;background:#15171c;color:#d9dce3;"
        "font:13px system-ui,sans-serif}"
        f"h1{{margin:0 0 {SHEET_GAP}px;font-size:15px;font-weight:600;color:#8a909c}}"
        f".grid{{display:grid;grid-template-columns:repeat({columns},max-content);gap:{SHEET_GAP}px;"
        "align-items:start}"
        "figure{margin:0}img{display:block;border-radius:8px;box-shadow:0 10px 30px rgba(0,0,0,.45)}"
        "figcaption{margin-top:6px;font-family:ui-monospace,Menlo,monospace;font-size:12px;color:#8a909c}"
        "figcaption b{color:#d9dce3;font-weight:500;margin-right:8px}"
        "</style>"
        f"<h1>{html.escape(title)}</h1><div class=grid>{''.join(cells)}</div>"
    )


def shoot(ns: argparse.Namespace) -> int:
    from ._browser import explain_error, load_playwright, new_context

    loaded = load_playwright()
    if loaded is None:
        return 2
    sync_playwright, playwright_error = loaded

    out = Path(ns.out)
    out.mkdir(parents=True, exist_ok=True)
    landscape = getattr(ns, "landscape", False)
    targets = list(
        zip(
            [(p, w) for p in ns.pages for w in ns.widths],
            planned_files(ns.pages, ns.widths, ns.height, landscape, out),
        )
    )
    entries: list[tuple[str, int, int, bytes]] = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            for (page_path, width), file in targets:
                w, h = (ns.height, width) if landscape else (width, ns.height)
                context = new_context(browser, ns, w, h)
                page = context.new_page()
                page.goto(ns.upstream + page_path, wait_until="networkidle", timeout=ns.timeout * 1000)
                page.wait_for_timeout(ns.settle * 1000)
                png = page.screenshot(path=str(file), full_page=ns.full_page)
                context.close()
                entries.append((page_path, w, h, png))
                print(f"wrote {file}")
            if entries and not getattr(ns, "no_sheet", False):
                columns = sheet_columns(len(ns.widths))
                sheet_w = sheet_viewport_width([e[1] for e in entries], columns)
                context = browser.new_context(
                    viewport={"width": sheet_w, "height": 800}, device_scale_factor=1
                )
                page = context.new_page()
                page.set_content(contact_sheet_html(entries, columns, f"{ns.upstream}  ·  wontfit"))
                page.screenshot(path=str(out / SHEET_NAME), full_page=True)
                context.close()
                print(f"wrote {out / SHEET_NAME}")
            browser.close()
    except playwright_error as exc:
        sys.stderr.write(f"wontfit shoot: {explain_error(exc)}\n")
        return 1
    return 0
