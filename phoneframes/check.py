"""``phoneframes check``: run the frame diagnostics headlessly and fail the build on demand.

The browser-driving part needs Playwright (optional, see :mod:`phoneframes._browser`).
Everything that shapes results, decides the exit code and formats the table is
pure and unit-tested.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

from . import CHECK_KINDS, __version__

# Runs inside the page after diagnostics.js; returns only JSON-safe data.
_COLLECT_JS = """
() => {
  const r = window.PhoneframesDiagnostics.analyze(document);
  return {
    overflow: r.overflow ? { amount: r.overflow.amount, culprits: r.overflow.culprits } : null,
    tapTargets: r.tapTargets.map(t => ({ label: t.label, width: t.width, height: t.height })),
    smallText: r.smallText
  };
}
"""


@dataclass
class FrameResult:
    """Diagnostics for one page at one viewport."""

    page: str
    width: int
    height: int
    overflow_px: int = 0
    culprits: list[dict[str, Any]] = field(default_factory=list)
    tap_targets: int = 0
    tap_target_list: list[dict[str, Any]] = field(default_factory=list)
    small_text: int = 0
    error: str | None = None

    @property
    def failed_kinds(self) -> list[str]:
        kinds = []
        if self.overflow_px > 0:
            kinds.append("overflow")
        if self.tap_targets > 0:
            kinds.append("taps")
        if self.small_text > 0:
            kinds.append("text")
        return kinds


def shape_result(page: str, width: int, height: int, raw: dict[str, Any]) -> FrameResult:
    """Turn the JSON the page script returns into a :class:`FrameResult`."""
    overflow = raw.get("overflow") or {}
    taps = list(raw.get("tapTargets") or [])
    return FrameResult(
        page=page,
        width=width,
        height=height,
        overflow_px=int(overflow.get("amount") or 0),
        culprits=list(overflow.get("culprits") or []),
        tap_targets=len(taps),
        tap_target_list=taps,
        small_text=int(raw.get("smallText") or 0),
    )


def failures(results: Sequence[FrameResult], fail_on: Sequence[str]) -> list[str]:
    """Human-readable lines for every frame that trips a selected check (or errored)."""
    selected = [k for k in CHECK_KINDS if k in fail_on]
    lines = []
    for r in results:
        if r.error:
            lines.append(f"{r.page} @ {r.width}: error: {r.error}")
            continue
        for kind in r.failed_kinds:
            if kind not in selected:
                continue
            if kind == "overflow":
                first = r.culprits[0]["label"] if r.culprits else "no element identified"
                lines.append(f"{r.page} @ {r.width}: overflow +{r.overflow_px}px ({first})")
            elif kind == "taps":
                lines.append(f"{r.page} @ {r.width}: {r.tap_targets} tap target(s) under 44x44")
            elif kind == "text":
                lines.append(f"{r.page} @ {r.width}: {r.small_text} element(s) with text under 12px")
    return lines


def exit_code(results: Sequence[FrameResult], fail_on: Sequence[str]) -> int:
    """0 when clean, 1 when a selected check failed or a page errored."""
    return 1 if failures(results, fail_on) else 0


def build_report(upstream: str, results: Sequence[FrameResult], fail_on: Sequence[str]) -> dict[str, Any]:
    """The JSON document ``--json`` writes."""
    return {
        "tool": "phoneframes",
        "version": __version__,
        "upstream": upstream,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "fail_on": list(fail_on),
        "ok": exit_code(results, fail_on) == 0,
        "failures": failures(results, fail_on),
        "results": [asdict(r) for r in results],
    }


def format_table(results: Sequence[FrameResult]) -> str:
    """A fixed-width table for the terminal."""
    rows = [("page", "size", "overflow", "small taps", "text<12px")]
    for r in results:
        if r.error:
            rows.append((r.page, f"{r.width}x{r.height}", "error", "-", "-"))
            continue
        over = f"+{r.overflow_px}px" if r.overflow_px else "fits"
        if r.overflow_px and r.culprits:
            over += f" ({r.culprits[0]['label']})"
        rows.append((r.page, f"{r.width}x{r.height}", over, str(r.tap_targets), str(r.small_text)))
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    out = []
    for n, row in enumerate(rows):
        out.append("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip())
        if n == 0:
            out.append("  ".join("-" * w for w in widths))
    return "\n".join(out)


def diagnostics_source() -> str:
    return resources.files("phoneframes").joinpath("assets", "diagnostics.js").read_text(encoding="utf-8")


def run_check(ns: argparse.Namespace) -> int:
    """Drive a headless Chromium through every page x width and report."""
    from ._browser import explain_error, load_playwright, new_context

    loaded = load_playwright()
    if loaded is None:
        return 2
    sync_playwright, playwright_error = loaded
    fail_on = list(ns.fail_on)
    source = diagnostics_source()
    results: list[FrameResult] = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            for page_path in ns.pages:
                for width in ns.widths:
                    w, h = (ns.height, width) if getattr(ns, "landscape", False) else (width, ns.height)
                    context = new_context(browser, ns, w, h, scale=1)
                    page = context.new_page()
                    try:
                        page.goto(
                            ns.upstream + page_path, wait_until="networkidle", timeout=ns.timeout * 1000
                        )
                        page.wait_for_timeout(ns.settle * 1000)
                        page.evaluate(source)
                        raw = page.evaluate(_COLLECT_JS)
                        results.append(shape_result(page_path, w, h, raw))
                    except playwright_error as exc:
                        results.append(FrameResult(page_path, w, h, error=explain_error(exc).splitlines()[0]))
                    finally:
                        context.close()
            browser.close()
    except playwright_error as exc:
        sys.stderr.write(f"phoneframes check: {explain_error(exc)}\n")
        return 1

    print(format_table(results))
    problems = failures(results, fail_on)
    if problems:
        print("\nFAIL (" + ", ".join(fail_on) + "):")
        for line in problems:
            print("  " + line)
    else:
        print(f"\nOK: no {', '.join(fail_on) or 'selected'} findings in {len(results)} frame(s)")
    if ns.json:
        Path(ns.json).write_text(
            json.dumps(build_report(ns.upstream, results, fail_on), indent=2), encoding="utf-8"
        )
        print(f"wrote {ns.json}")
    return exit_code(results, fail_on)
