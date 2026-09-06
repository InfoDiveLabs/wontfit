"""Command line entry point: ``phoneframes`` (serve) and ``phoneframes shoot``."""

from __future__ import annotations

import argparse
import sys
import webbrowser
from collections.abc import Sequence

from . import PRESETS, __version__
from .proxy import ProxyConfig

DEFAULT_UPSTREAM = "http://localhost:3000"
DEFAULT_PORT = 8081
DEFAULT_WIDTHS = [375, 393, 430]
DEFAULT_HEIGHT = 800


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


# --- parser --------------------------------------------------------------------------


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


def build_parser() -> argparse.ArgumentParser:
    """The ``serve`` parser (the default command)."""
    parser = argparse.ArgumentParser(
        prog="phoneframes",
        description="Preview a local web app at phone and tablet sizes, side by side, in a desktop browser.",
        epilog="Screenshots: phoneframes shoot --help",
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
        description="Write PNG screenshots of each page at each width using Playwright (optional extra).",
    )
    _shared(parser)
    parser.add_argument("--out", default="shots", help="output directory (default ./shots)")
    parser.add_argument(
        "--full-page", action="store_true", help="capture the whole scrollable page, not just the viewport"
    )
    parser.add_argument("--landscape", action="store_true", help="swap width and height")
    return parser


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse ``argv`` into a namespace with a ``command`` of ``serve`` or ``shoot``."""
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "shoot":
        ns = build_shoot_parser().parse_args(args[1:])
        ns.command = "shoot"
    else:
        ns = build_parser().parse_args(args)
        ns.command = "serve"
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


def main(argv: Sequence[str] | None = None) -> int:
    ns = parse_args(argv)
    if ns.command == "shoot":
        from .shoot import shoot

        return shoot(ns)
    return serve(ns)


if __name__ == "__main__":
    raise SystemExit(main())
