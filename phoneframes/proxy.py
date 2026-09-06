"""The reverse proxy: forwards everything to the upstream app, minus the frame-blocking headers.

Design notes
------------
* Uses :mod:`http.client` rather than :mod:`urllib.request` so redirects are
  *not* followed (the browser must see them) and bodies can be streamed.
* Bodies are never decoded: ``Content-Encoding`` (gzip, br, zstd) passes
  through untouched, so the proxy never needs a decompressor.
* One fresh upstream connection per request. Simple, thread-safe, slightly
  slower than pooling; fine for a dev tool.
* Deliberately not handled: WebSockets (the ``Upgrade`` handshake is refused
  with 501), HTTP/2 push, trailers, and request bodies with unknown length.

All header manipulation lives in small pure functions so it can be unit-tested
without sockets: :func:`strip_frame_ancestors`, :func:`rewrite_location`,
:func:`rewrite_set_cookie`, :func:`build_upstream_headers`, and
:func:`filter_response_headers`.
"""

from __future__ import annotations

import http.client
import http.server
import json
import socket
import ssl
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Iterable, List, Optional, Tuple
from urllib.parse import urlsplit

from . import HARNESS_PATH, __version__

Header = Tuple[str, str]
Headers = List[Header]

#: Headers that describe the connection, not the message. Never forwarded either way.
HOP_BY_HOP = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "proxy-connection",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
    }
)

CHUNK = 64 * 1024
DEFAULT_PORTS = {"http": 80, "https": 443}


def origin_of(url: str) -> Tuple[str, str, int]:
    """Return ``(scheme, host, port)`` for a URL, filling in the default port."""
    parts = urlsplit(url)
    scheme = (parts.scheme or "http").lower()
    host = (parts.hostname or "localhost").lower()
    port = parts.port or DEFAULT_PORTS.get(scheme, 80)
    return scheme, host, port


def same_origin(a: str, b: str) -> bool:
    """True when two URLs share scheme, host and effective port."""
    return origin_of(a) == origin_of(b)


def _netloc(url: str) -> str:
    """The ``host[:port]`` for a URL, omitting a default port."""
    scheme, host, port = origin_of(url)
    if port == DEFAULT_PORTS.get(scheme):
        return host
    return f"{host}:{port}"


def strip_frame_ancestors(csp: str) -> Optional[str]:
    """Remove the ``frame-ancestors`` directive from a CSP value, keeping the rest.

    Returns ``None`` when nothing is left, meaning the header should be dropped.
    Directive names are matched case-insensitively per the CSP spec.
    """
    kept = []
    for directive in csp.split(";"):
        name = directive.strip().split(None, 1)[0].lower() if directive.strip() else ""
        if name == "frame-ancestors":
            continue
        if directive.strip():
            kept.append(directive.strip())
    return "; ".join(kept) if kept else None


def rewrite_location(value: str, upstream: str, proxy_origin: str) -> str:
    """Point an absolute redirect at the proxy when it targets the upstream origin.

    Relative Locations are left alone (the browser resolves them against the
    proxy already). Absolute Locations to other origins are left alone too.
    """
    stripped = value.strip()
    if "://" not in stripped:
        return value
    if not same_origin(stripped, upstream):
        return value
    parts = urlsplit(stripped)
    rest = parts.path or "/"
    if parts.query:
        rest += "?" + parts.query
    if parts.fragment:
        rest += "#" + parts.fragment
    return proxy_origin.rstrip("/") + rest


def rewrite_origin_header(value: str, upstream: str, proxy_origin: str) -> str:
    """The inverse of :func:`rewrite_location`: proxy origin -> upstream origin.

    Applied to ``Origin`` and ``Referer`` so CSRF origin checks in the app see
    the host they expect.
    """
    stripped = value.strip()
    if "://" not in stripped or not same_origin(stripped, proxy_origin):
        return value
    parts = urlsplit(stripped)
    rest = parts.path  # empty for a bare Origin such as "http://127.0.0.1:8081"
    if parts.query:
        rest += "?" + parts.query
    return upstream.rstrip("/") + rest


def rewrite_set_cookie(value: str) -> str:
    """Make an upstream ``Set-Cookie`` storable for the proxy's plain-HTTP loopback origin.

    * ``Domain=`` is removed so the cookie defaults to the proxy host.
    * ``Secure`` is removed because the proxy speaks plain HTTP.
    * ``SameSite=None`` (which requires ``Secure``) becomes ``SameSite=Lax``;
      the harness frames are same-origin so Lax is sufficient.
    """
    parts = [p.strip() for p in value.split(";")]
    out = [parts[0]]
    for attr in parts[1:]:
        key, _, val = attr.partition("=")
        k = key.strip().lower()
        if k in ("domain", "secure"):
            continue
        if k == "samesite" and val.strip().lower() == "none":
            out.append("SameSite=Lax")
            continue
        if attr:
            out.append(attr)
    return "; ".join(out)


@dataclass
class ProxyConfig:
    """Everything the proxy needs to know. Built by the CLI, consumed by the handler."""

    upstream: str = "http://localhost:3000"
    host: str = "127.0.0.1"
    port: int = 8081
    cookies: List[Tuple[str, str]] = field(default_factory=list)
    headers: List[Tuple[str, str]] = field(default_factory=list)
    insecure: bool = False
    #: Value for the upstream ``Host`` header. ``"preserve"`` forwards the browser's.
    rewrite_host: Optional[str] = None
    verbose: bool = False
    timeout: float = 30.0

    @property
    def proxy_origin(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def upstream_is_tls(self) -> bool:
        return origin_of(self.upstream)[0] == "https"

    def upstream_host_header(self, client_host: Optional[str]) -> str:
        """Pick the ``Host`` value to send upstream (see ``--rewrite-host``)."""
        if self.rewrite_host == "preserve":
            return client_host or _netloc(self.upstream)
        if self.rewrite_host:
            return self.rewrite_host
        return _netloc(self.upstream)

    def ssl_context(self) -> Optional[ssl.SSLContext]:
        if not self.upstream_is_tls:
            return None
        ctx = ssl.create_default_context()
        if self.insecure:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        return ctx

    def connect(self) -> http.client.HTTPConnection:
        """Open a fresh connection to the upstream."""
        _, host, port = origin_of(self.upstream)
        if self.upstream_is_tls:
            return http.client.HTTPSConnection(host, port, timeout=self.timeout, context=self.ssl_context())
        return http.client.HTTPConnection(host, port, timeout=self.timeout)


def build_upstream_headers(config: ProxyConfig, incoming: Iterable[Header]) -> Headers:
    """Turn the browser's request headers into the headers sent upstream.

    Drops hop-by-hop headers, replaces ``Host``, rewrites ``Origin``/``Referer``,
    merges ``--cookie`` values into ``Cookie`` and appends ``--header`` extras.
    """
    out: Headers = []
    client_host: Optional[str] = None
    cookie_parts: List[str] = []
    for name, value in incoming:
        lname = name.lower()
        if lname in HOP_BY_HOP:
            continue
        if lname == "host":
            client_host = value
            continue
        if lname == "cookie":
            cookie_parts.append(value)
            continue
        if lname in ("origin", "referer") and config.rewrite_host != "preserve":
            value = rewrite_origin_header(value, config.upstream, config.proxy_origin)
        out.append((name, value))
    out.insert(0, ("Host", config.upstream_host_header(client_host)))
    extra_cookies = [f"{k}={v}" for k, v in config.cookies]
    if cookie_parts or extra_cookies:
        out.append(("Cookie", "; ".join(cookie_parts + extra_cookies)))
    out.extend(config.headers)
    return out


def filter_response_headers(config: ProxyConfig, upstream_headers: Iterable[Header]) -> Headers:
    """Rewrite the upstream response headers for the browser.

    * ``X-Frame-Options`` is dropped.
    * ``frame-ancestors`` is stripped from ``Content-Security-Policy`` (and the
      report-only variant); the rest of the policy is kept.
    * Absolute ``Location`` to the upstream is rewritten to the proxy.
    * ``Set-Cookie`` is made storable on the proxy origin.
    * Hop-by-hop headers and ``Content-Length`` are dropped; the handler
      decides framing itself.
    """
    out: Headers = []
    for name, value in upstream_headers:
        lname = name.lower()
        if lname in HOP_BY_HOP or lname in ("x-frame-options", "content-length"):
            continue
        if lname in ("content-security-policy", "content-security-policy-report-only"):
            stripped = strip_frame_ancestors(value)
            if stripped is None:
                continue
            value = stripped
        elif lname in ("location", "content-location"):
            value = rewrite_location(value, config.upstream, config.proxy_origin)
        elif lname == "set-cookie":
            value = rewrite_set_cookie(value)
        out.append((name, value))
    return out


class UpstreamError(Exception):
    """The upstream could not be reached or answered garbage."""


def _read_chunked(rfile) -> bytes:
    """Read a chunked request body (rare from browsers, but cheap to support)."""
    body = bytearray()
    while True:
        line = rfile.readline().strip()
        size = int(line.split(b";")[0] or b"0", 16)
        if size == 0:
            while rfile.readline().strip():  # trailers
                pass
            return bytes(body)
        body += rfile.read(size)
        rfile.readline()  # CRLF after chunk


HarnessRoute = Callable[["ProxyHandler", str], bool]


class ProxyHandler(http.server.BaseHTTPRequestHandler):
    """One request in, one upstream request out. Harness paths are served locally."""

    protocol_version = "HTTP/1.1"
    server_version = f"phoneframes/{__version__}"
    sys_version = ""
    config: ProxyConfig = ProxyConfig()
    #: Called for ``/__phoneframes*`` paths. Returns True when it handled the request.
    harness_route: Optional[HarnessRoute] = None

    # -- plumbing -----------------------------------------------------------------

    def log_message(self, fmt: str, *args) -> None:  # noqa: D401 - BaseHTTPRequestHandler API
        if self.config.verbose:
            sys.stderr.write("phoneframes: %s\n" % (fmt % args))

    def send_text(self, status: int, text: str, content_type: str = "text/plain; charset=utf-8") -> None:
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def send_json(self, payload: object, status: int = 200) -> None:
        self.send_text(status, json.dumps(payload), "application/json")

    # -- dispatch -----------------------------------------------------------------

    def _dispatch(self) -> None:
        path_only = self.path.split("?", 1)[0]
        if path_only == HARNESS_PATH or path_only.startswith(HARNESS_PATH + "/"):
            if self.harness_route and self.harness_route(self, path_only):
                return
            self.send_text(404, "phoneframes: no such harness route")
            return
        self._proxy()

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = do_OPTIONS = _dispatch

    # -- the proxy ----------------------------------------------------------------

    def _read_request_body(self) -> Optional[bytes]:
        if "chunked" in (self.headers.get("Transfer-Encoding") or "").lower():
            return _read_chunked(self.rfile)
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length) if length else None

    def _proxy(self) -> None:
        if (self.headers.get("Upgrade") or "").lower() == "websocket":
            self.send_text(501, "phoneframes does not proxy WebSockets; talk to the upstream directly.")
            return
        body = self._read_request_body()
        headers = build_upstream_headers(self.config, self.headers.items())
        started = time.monotonic()
        try:
            conn = self.config.connect()
            conn.putrequest(self.command, self.path, skip_host=True, skip_accept_encoding=True)
            for name, value in headers:
                conn.putheader(name, value)
            if body is not None and not any(n.lower() == "content-length" for n, _ in headers):
                conn.putheader("Content-Length", str(len(body)))
            conn.endheaders(body)
            resp = conn.getresponse()
        except ssl.SSLCertVerificationError as exc:
            self.send_text(502, f"phoneframes: TLS verification failed for {self.config.upstream}: {exc}\n"
                                "Pass --insecure to accept a self-signed certificate.")
            return
        except (OSError, http.client.HTTPException) as exc:
            self.send_text(502, f"phoneframes: upstream {self.config.upstream} unreachable: {exc}")
            return

        try:
            self._relay_response(resp)
        except (BrokenPipeError, ConnectionResetError):
            pass  # browser went away mid-stream; nothing to do
        finally:
            conn.close()
        if self.config.verbose:
            ms = int((time.monotonic() - started) * 1000)
            self.log_message('"%s %s" %s %dms', self.command, self.path, resp.status, ms)

    def _relay_response(self, resp: http.client.HTTPResponse) -> None:
        self.send_response_only(resp.status, resp.reason)
        for name, value in filter_response_headers(self.config, resp.getheaders()):
            self.send_header(name, value)

        upstream_length = resp.getheader("Content-Length")
        bodiless = self.command == "HEAD" or resp.status in (204, 304) or 100 <= resp.status < 200
        chunked = False
        if bodiless:
            if upstream_length is not None:
                self.send_header("Content-Length", upstream_length)
            else:
                self.send_header("Content-Length", "0")
        elif upstream_length is not None:
            self.send_header("Content-Length", upstream_length)
        elif self.request_version == "HTTP/1.1":
            self.send_header("Transfer-Encoding", "chunked")
            chunked = True
        else:
            self.close_connection = True
        self.end_headers()
        if bodiless:
            return

        while True:
            chunk = resp.read(CHUNK)
            if not chunk:
                break
            if chunked:
                self.wfile.write(b"%x\r\n%s\r\n" % (len(chunk), chunk))
            else:
                self.wfile.write(chunk)
        if chunked:
            self.wfile.write(b"0\r\n\r\n")
        self.wfile.flush()


class ProxyServer(http.server.ThreadingHTTPServer):
    """A threading HTTP server bound to loopback that carries the proxy config."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, config: ProxyConfig, harness_route: Optional[HarnessRoute] = None):
        handler = type("ConfiguredProxyHandler", (ProxyHandler,), {"config": config, "harness_route": harness_route})
        super().__init__((config.host, config.port), handler)
        self.config = config
        config.port = self.server_address[1]  # resolve port 0 to the real one

    def serve_in_thread(self) -> threading.Thread:
        """Start serving on a daemon thread (used by tests and by ``shoot``)."""
        thread = threading.Thread(target=self.serve_forever, name="phoneframes-proxy", daemon=True)
        thread.start()
        return thread


def wait_for_port(host: str, port: int, timeout: float = 5.0) -> bool:
    """Block until something accepts TCP connections on ``host:port`` (or time out)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.2):
                return True
        except OSError:
            time.sleep(0.05)
    return False
