"""The harness page (``/__wontfit``) and its small JSON endpoints.

The page itself is a static asset (``assets/harness.html``) with the
diagnostics script (``assets/diagnostics.js``) inlined at render time, plus a
JSON blob describing the initial layout. Both assets are loaded with
:mod:`importlib.resources` so the package works zipped or installed.

Layout state (pages, widths, height, orientation, live reload) round-trips
through the query string so any arrangement is a shareable deep link. The
serialisation is defined here in Python and mirrored in the page's script;
:class:`HarnessState` is the source of truth and is unit tested.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from importlib import resources
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlencode

from . import HARNESS_PATH, PRESETS, __version__

if TYPE_CHECKING:  # pragma: no cover
    from .proxy import HarnessRoute, ProxyHandler
    from .watch import Watcher

DIAGNOSTICS_PLACEHOLDER = "/*__WONTFIT_DIAGNOSTICS__*/"
CONFIG_PLACEHOLDER = "/*__WONTFIT_CONFIG__*/null"


@dataclass
class HarnessState:
    """What the harness is showing. Serialises to and from a query string.

    Keys are short because they live in the address bar: ``p`` pages, ``w``
    widths, ``h`` height, ``o=l`` landscape, ``live=0`` disables reload.
    """

    pages: list[str] = field(default_factory=lambda: ["/"])
    widths: list[int] = field(default_factory=lambda: [375, 393, 430])
    height: int = 800
    landscape: bool = False
    live: bool = True

    def to_query(self) -> str:
        params: dict[str, str] = {
            "p": ",".join(self.pages),
            "w": ",".join(str(w) for w in self.widths),
            "h": str(self.height),
        }
        if self.landscape:
            params["o"] = "l"
        if not self.live:
            params["live"] = "0"
        return urlencode(params, safe="/,")

    @classmethod
    def from_query(cls, query: str, default: HarnessState | None = None) -> HarnessState:
        """Parse a query string, falling back to ``default`` for anything missing or invalid."""
        base = default or cls()
        q = parse_qs(query.lstrip("?"), keep_blank_values=False)

        def first(key: str) -> str | None:
            values = q.get(key)
            return values[0] if values else None

        pages = [p.strip() for p in (first("p") or "").split(",") if p.strip()]
        widths: list[int] = []
        for token in (first("w") or "").split(","):
            token = token.strip().lower()
            if token in PRESETS:
                widths.append(PRESETS[token][1])
            elif token.isdigit() and 100 <= int(token) <= 4000:
                widths.append(int(token))
        height_text = first("h") or ""
        height = (
            int(height_text) if height_text.isdigit() and 100 <= int(height_text) <= 4000 else base.height
        )
        return cls(
            pages=[p if p.startswith("/") else "/" + p for p in pages] or list(base.pages),
            widths=widths or list(base.widths),
            height=height,
            landscape=first("o") == "l",
            live=first("live") != "0",
        )

    def url(self, origin: str) -> str:
        return f"{origin.rstrip('/')}{HARNESS_PATH}?{self.to_query()}"

    def frames(self) -> list[dict[str, object]]:
        """One entry per page x width, with orientation applied."""
        out: list[dict[str, object]] = []
        for page in self.pages:
            for width in self.widths:
                w, h = (self.height, width) if self.landscape else (width, self.height)
                out.append({"page": page, "width": w, "height": h, "device": width})
        return out


def _asset(name: str) -> str:
    return resources.files("wontfit").joinpath("assets", name).read_text(encoding="utf-8")


def harness_config(state: HarnessState, watch_interval: float, watch_description: str) -> dict[str, object]:
    """The JSON handed to the page script on load."""
    return {
        "version": __version__,
        "path": HARNESS_PATH,
        "pages": state.pages,
        "widths": state.widths,
        "height": state.height,
        "landscape": state.landscape,
        "live": state.live,
        "presets": [{"key": key, "name": name, "width": width} for key, (name, width) in PRESETS.items()],
        "watch": {"interval": watch_interval, "description": watch_description},
    }


def render_harness(state: HarnessState, watch_interval: float = 2.0, watch_description: str = "") -> str:
    """Assemble the harness HTML: template + inlined diagnostics + config JSON."""
    html = _asset("harness.html")
    diagnostics = _asset("diagnostics.js")
    config_json = json.dumps(harness_config(state, watch_interval, watch_description)).replace("</", "<\\/")
    return html.replace(DIAGNOSTICS_PLACEHOLDER, diagnostics).replace(CONFIG_PLACEHOLDER, config_json)


def make_route(state: HarnessState, watcher: Watcher, watch_interval: float) -> HarnessRoute:
    """Build the handler callback for ``/__wontfit`` and ``/__wontfit/watch``."""

    def route(handler: ProxyHandler, path: str) -> bool:
        if path == HARNESS_PATH or path == HARNESS_PATH + "/":
            if handler.command not in ("GET", "HEAD"):
                handler.send_text(405, "GET only")
                return True
            html = render_harness(state, watch_interval, watcher.detector.describe())
            handler.send_text(200, html, "text/html; charset=utf-8")
            return True
        if path == HARNESS_PATH + "/watch":
            handler.send_json(watcher.status())
            return True
        if path == HARNESS_PATH + "/health":
            handler.send_json({"ok": True, "version": __version__})
            return True
        return False

    return route
