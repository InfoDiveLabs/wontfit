"""Command line entry point.

``phoneframes``        serve the proxy and harness (the default command)
``phoneframes shoot``  PNG screenshots plus a contact sheet (needs Playwright)
``phoneframes check``  headless diagnostics with a CI-friendly exit code (needs Playwright)
``phoneframes init``   write a starter ``phoneframes.toml``

A ``phoneframes.toml`` (or ``[tool.phoneframes]`` in ``pyproject.toml``) found in
the current directory or any parent supplies defaults; flags override it.
"""

from __future__ import annotations

import argparse
import sys
import webbrowser
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from . import CHECK_KINDS, PRESETS, __version__
from .config import FILE_NAME, ConfigError, find_config, to_cli_defaults, write_starter
from .proxy import ProxyConfig

DEFAULT_UPSTREAM = "http://localhost:3000"
DEFAULT_PORT = 8081
DEFAULT_WIDTHS = [375, 393, 430]
DEFAULT_HEIGHT = 800
COMMANDS = ("serve", "shoot", "check", "init")


# --- value parsers (exposed for tests) ---------------------------------------------


def parse_cookie(text: str) -> tuple[str, str]:
    """``name=value`` -> ``("name", "value")``."""
    name, sep, value = text.partition("=")
    if not sep or not name.strip():
        raise argparse.ArgumentTypeError(f"cookie must look like name=value, got {text!r}")
    return name.strip(), value.strip()


def parse_header(text: str) -> tuple[str, str]:
    """``Name: value`` -> ``("Name", "value")``."""
    name, sep, value = text.partition(":")
    if not sep or not name.strip():
        raise argparse.ArgumentTypeError(f"header must look like 'Name: value', got {text!r}")
    return name.strip(), value.strip()


def parse_pages(text: str) -> list[str]:
    """Comma-separated paths; each gets a leading slash."""
    pages = []
    for raw in text.split(","):
        page = raw.strip()
        if not page:
            continue
        if not page.startswith("/"):
            page = "/" + page
        pages.append(page)
    if not pages:
        raise argparse.ArgumentTypeError("at least one page is required")
    return pages


def parse_widths(text: str) -> list[int]:
    """Comma-separated CSS widths; numbers or preset keys such as ``se``, ``pixel8``."""
    widths = []
    for raw in text.split(","):
        token = raw.strip().lower().replace(" ", "")
        if not token:
            continue
        if token in PRESETS:
            widths.append(PRESETS[token][1])
            continue
        try:
            value = int(token)
        except ValueError:
            names = ", ".join(PRESETS)
            raise argparse.ArgumentTypeError(
                f"unknown width {raw!r}; use a number or one of: {names}"
            ) from None
        if not 100 <= value <= 4000:
            raise argparse.ArgumentTypeError(f"width {value} is outside 100..4000")
        widths.append(value)
    if not widths:
        raise argparse.ArgumentTypeError("at least one width is required")
    return widths


def parse_upstream(text: str) -> str:
    """Normalise the upstream URL: add a scheme when missing, strip a trailing slash."""
    url = text.strip()
    if "://" not in url:
        url = "http://" + url
    return url.rstrip("/")


def parse_fail_on(text: str) -> list[str]:
    """``overflow,taps`` -> list; ``none`` -> empty list."""
    kinds = [k.strip().lower() for k in text.split(",") if k.strip()]
    if kinds == ["none"]:
        return []
    bad = [k for k in kinds if k not in CHECK_KINDS]
    if bad:
        raise argparse.ArgumentTypeError(
            f"unknown check(s) {', '.join(bad)}; choose from {', '.join(CHECK_KINDS)} or none"
        )
    return kinds


# --- parsers -------------------------------------------------------------------------


def _shared(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--upstream",
        type=parse_upstream,
        default=DEFAULT_UPSTREAM,
        help=f"the app to preview (default {DEFAULT_UPSTREAM})",
    )
    parser.add_argument(
        "--pages",
        type=parse_pages,
        default=["/"],
        metavar="/a,/b",
        help="comma-separated paths to open (default /)",
    )
    parser.add_argument(
        "--widths",
        type=parse_widths,
        default=list(DEFAULT_WIDTHS),
        metavar="375,se,ipad",
        help="comma-separated CSS widths or preset names (default 375,393,430)",
    )
    parser.add_argument(
        "--height", type=int, default=DEFAULT_HEIGHT, help=f"frame height in px (default {DEFAULT_HEIGHT})"
    )
    parser.add_argument(
        "--cookie",
        type=parse_cookie,
        action="append",
        default=[],
        metavar="name=value",
        help="cookie sent with every upstream request (repeatable)",
    )
    parser.add_argument(
        "--header",
        type=parse_header,
        action="append",
        default=[],
        metavar="'Name: value'",
        help="header sent with every upstream request (repeatable)",
    )
    parser.add_argument(
        "--insecure", action="store_true", help="accept self-signed HTTPS upstream certificates"
    )
    parser.add_argument(
        "--no-config", action="store_true", help=f"ignore any {FILE_NAME} / pyproject.toml [tool.phoneframes]"
    )


def _browser_shared(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--landscape", action="store_true", help="swap width and height")
    parser.add_argument(
        "--timeout", type=float, default=30.0, metavar="SECONDS", help="page load timeout (default 30)"
    )
    parser.add_argument(
        "--settle",
        type=float,
        default=0.5,
        metavar="SECONDS",
        help="wait after load before measuring or capturing (default 0.5)",
    )


def build_parser() -> argparse.ArgumentParser:
    """The ``serve`` parser (the default command)."""
    parser = argparse.ArgumentParser(
        prog="phoneframes",
        description="Preview a local web app at phone and tablet sizes, side by side, in a desktop browser.",
        epilog="Subcommands: phoneframes shoot | check | init  (each has --help)",
    )
    parser.add_argument("--version", action="version", version=f"phoneframes {__version__}")
    _shared(parser)
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"port to listen on, loopback only (default {DEFAULT_PORT})",
    )
    parser.add_argument("--open", action="store_true", help="open the harness in your default browser")
    parser.add_argument(
        "--rewrite-host",
        metavar="HOST",
        default=None,
        help="Host header to send upstream: a literal value, or 'preserve' to forward the "
        "browser's (default: the upstream's own host)",
    )
    parser.add_argument(
        "--watch-url",
        metavar="URL",
        default=None,
        help="poll this URL for changes and reload frames (default: the first page)",
    )
    parser.add_argument(
        "--watch-file",
        metavar="GLOB",
        action="append",
        default=[],
        help="watch local files by mtime instead of, or as well as, a URL (repeatable, ** allowed)",
    )
    parser.add_argument(
        "--watch-interval",
        type=float,
        default=2.0,
        metavar="SECONDS",
        help="how often the harness checks for changes (default 2)",
    )
    parser.add_argument("--no-watch", action="store_true", help="disable live reload")
    parser.add_argument("-v", "--verbose", action="store_true", help="log every proxied request")
    return parser


def build_shoot_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="phoneframes shoot",
        description="Write a PNG per page x width plus a contact sheet, using Playwright (optional extra).",
    )
    _shared(parser)
    _browser_shared(parser)
    parser.add_argument("--out", default="shots", help="output directory (default ./shots)")
    parser.add_argument(
        "--full-page", action="store_true", help="capture the whole scrollable page, not just the viewport"
    )
    parser.add_argument("--no-sheet", action="store_true", help="skip the tiled contact-sheet PNG")
    return parser


def build_check_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="phoneframes check",
        description="Run the overflow / tap-target / small-text diagnostics headlessly and exit non-zero "
        "on selected findings, using Playwright (optional extra).",
    )
    _shared(parser)
    _browser_shared(parser)
    parser.add_argument(
        "--fail-on",
        type=parse_fail_on,
        default=["overflow"],
        metavar="overflow,taps,text",
        help="which findings fail the run (default overflow; 'none' to only report)",
    )
    parser.add_argument("--json", metavar="PATH", default=None, help="also write a JSON report here")
    return parser


def build_init_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="phoneframes init",
        description=f"Write a commented starter {FILE_NAME} in the current directory.",
    )
    parser.add_argument("--upstream", type=parse_upstream, default=None, help="pre-fill the upstream URL")
    parser.add_argument("--path", default=FILE_NAME, help=f"where to write (default ./{FILE_NAME})")
    parser.add_argument("--force", action="store_true", help="overwrite an existing file")
    return parser


PARSERS = {
    "serve": build_parser,
    "shoot": build_shoot_parser,
    "check": build_check_parser,
    "init": build_init_parser,
}


def apply_config_defaults(parser: argparse.ArgumentParser, defaults: dict[str, Any]) -> None:
    """Install config values as parser defaults, ignoring keys this parser does not have."""
    known = {action.dest for action in parser._actions}
    parser.set_defaults(**{k: v for k, v in defaults.items() if k in known})


def parse_args(argv: Sequence[str] | None = None, config_dir: Path | None = None) -> argparse.Namespace:
    """Parse ``argv``; ``ns.command`` is one of :data:`COMMANDS`, ``ns.config_path`` the file used."""
    args = list(sys.argv[1:] if argv is None else argv)
    command = "serve"
    if args and args[0] in COMMANDS:
        command = args.pop(0)
    parser = PARSERS[command]()

    config_path: Path | None = None
    if command != "init" and "--no-config" not in args:
        try:
            found = find_config(config_dir)
            if found:
                config_path, data = found
                apply_config_defaults(parser, to_cli_defaults(data))
        except ConfigError as exc:
            parser.error(f"config: {exc}")

    ns = parser.parse_args(args)
    ns.command = command
    ns.config_path = config_path
    if command == "serve":
        if ns.watch_url is None and not ns.watch_file and not ns.no_watch:
            ns.watch_url = ns.pages[0]
        if ns.no_watch:
            ns.watch_url = None
            ns.watch_file = []
    return ns


def config_from_args(ns: argparse.Namespace) -> ProxyConfig:
    return ProxyConfig(
        upstream=ns.upstream,
        port=getattr(ns, "port", 0),
        cookies=list(ns.cookie),
        headers=list(ns.header),
        insecure=ns.insecure,
        rewrite_host=getattr(ns, "rewrite_host", None),
        verbose=getattr(ns, "verbose", False),
    )


# --- commands ------------------------------------------------------------------------


def serve(ns: argparse.Namespace) -> int:
    from .harness import HarnessState, make_route
    from .proxy import ProxyServer
    from .watch import Watcher, build_detector

    config = config_from_args(ns)
    state = HarnessState(pages=ns.pages, widths=ns.widths, height=ns.height)
    detector = build_detector(config, ns.watch_url, ns.watch_file)
    watcher = Watcher(detector, min_interval=max(0.5, ns.watch_interval / 2))
    try:
        server = ProxyServer(config, make_route(state, watcher, ns.watch_interval))
    except OSError as exc:
        print(f"phoneframes: cannot listen on 127.0.0.1:{config.port}: {exc}", file=sys.stderr)
        return 1
    url = state.url(config.proxy_origin)
    print(f"phoneframes {__version__}: proxying {config.upstream} on {config.proxy_origin}")
    if ns.config_path:
        print(f"  config   {ns.config_path}")
    print(f"  harness  {url}")
    print(f"  reload   {detector.describe()}")
    print("  loopback only; never expose this port. Ctrl+C to stop.", flush=True)
    if ns.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nphoneframes: bye")
    finally:
        server.server_close()
    return 0


def init(ns: argparse.Namespace) -> int:
    path = Path(ns.path)
    if path.exists() and ns.force:
        path.unlink()
    try:
        write_starter(path, ns.upstream)
    except FileExistsError:
        print(f"phoneframes init: {path} exists; pass --force to overwrite", file=sys.stderr)
        return 1
    print(f"wrote {path}; edit it, commit it, and contributors can just run `phoneframes`")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    ns = parse_args(argv)
    if ns.command == "shoot":
        from .shoot import shoot

        return shoot(ns)
    if ns.command == "check":
        from .check import run_check

        return run_check(ns)
    if ns.command == "init":
        return init(ns)
    return serve(ns)


if __name__ == "__main__":
    raise SystemExit(main())
