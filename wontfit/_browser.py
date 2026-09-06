"""Shared Playwright plumbing for the optional ``shoot`` and ``check`` commands.

Playwright is never imported at module load; :func:`load_playwright` does it on
demand and prints an install hint when it is missing, so the core stays
dependency-free.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

INSTALL_HINT = (
    "This command needs Playwright, which is optional:\n"
    "    pip install 'wontfit[shoot]'   # or: pip install playwright\n"
    "    playwright install chromium\n"
)


def load_playwright() -> tuple[Any, Any] | None:
    """Return ``(sync_playwright, PlaywrightError)`` or ``None`` after printing the hint."""
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError:
        sys.stderr.write(INSTALL_HINT)
        return None
    return sync_playwright, PlaywrightError


def new_context(browser: Any, ns: argparse.Namespace, width: int, height: int, scale: int = 2) -> Any:
    """A fresh browser context with the CLI's cookies, headers and TLS setting applied."""
    context = browser.new_context(
        viewport={"width": width, "height": height},
        device_scale_factor=scale,
        ignore_https_errors=ns.insecure,
        extra_http_headers=dict(ns.header),
        bypass_csp=True,  # lets check() evaluate diagnostics on pages with strict script-src
    )
    if ns.cookie:
        context.add_cookies([{"name": k, "value": v, "url": ns.upstream + "/"} for k, v in ns.cookie])
    return context


def explain_error(exc: Exception) -> str:
    text = str(exc)
    if "Executable doesn't exist" in text or "playwright install" in text:
        return f"{text}\nRun: playwright install chromium"
    return text
