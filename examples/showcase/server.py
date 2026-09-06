#!/usr/bin/env python3
"""Ledgerly: a fake product site plus app dashboard that refuses to be framed.

    python3 examples/showcase/server.py            # http://localhost:3939
    phoneframes --upstream http://localhost:3939 --pages /,/pricing,/dashboard,/terms --open

Every response carries ``X-Frame-Options: DENY`` and a CSP with
``frame-ancestors 'none'``, so a plain iframe of it is blank and phoneframes'
proxy is doing visible work. The pages are decent responsive HTML with six
mobile bugs planted on purpose (see README.md in this directory).

Standard library only. Do not use as an example of a good server.
"""

from __future__ import annotations

import argparse
import http.server
import mimetypes
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

SITE = Path(__file__).resolve().parent / "site"
PAGES = {
    "/": "index.html",
    "/pricing": "pricing.html",
    "/dashboard": "dashboard.html",
    "/terms": "terms.html",
}
COOKIE = "ledgerly_session"
CSP = "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; frame-ancestors 'none'"


class Ledgerly(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # quiet
        pass

    def _headers(self, status, ctype, length, extra=()):
        self.send_response(status)
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        for k, v in extra:
            self.send_header(k, v)
        self.send_header("Content-Length", str(length))
        self.end_headers()

    def _send(self, status, body: bytes, ctype="text/html; charset=utf-8", extra=()):
        self._headers(status, ctype, len(body), extra)
        if self.command != "HEAD":
            self.wfile.write(body)

    def _cookie(self):
        for part in (self.headers.get("Cookie") or "").split(";"):
            name, _, value = part.strip().partition("=")
            if name == COOKIE:
                return value
        return None

    def do_GET(self):
        url = urlsplit(self.path)
        path = url.path
        host = self.headers.get("Host", "localhost")
        if path == "/login":
            # Absolute Location on purpose: phoneframes must rewrite it back to the proxy.
            self._send(
                302,
                b"",
                extra=[
                    ("Location", f"http://{host}/dashboard?welcome=1"),
                    (
                        "Set-Cookie",
                        f"{COOKIE}=demo-user; Path=/; HttpOnly; Secure; SameSite=None; Domain=localhost",
                    ),
                ],
            )
            return
        if path == "/logout":
            self._send(302, b"", extra=[("Location", "/"), ("Set-Cookie", f"{COOKIE}=; Path=/; Max-Age=0")])
            return
        if path.startswith("/static/"):
            file = SITE / path[len("/static/") :]
            if file.is_file() and SITE in file.resolve().parents:
                ctype = mimetypes.guess_type(str(file))[0] or "application/octet-stream"
                self._send(200, file.read_bytes(), ctype)
            else:
                self._send(404, b"not found", "text/plain")
            return
        page = PAGES.get(path)
        if not page:
            self._send(404, (SITE / "404.html").read_bytes())
            return
        html = (SITE / page).read_text(encoding="utf-8")
        if page == "dashboard.html":
            user = self._cookie()
            welcome = "welcome" in parse_qs(url.query)
            if user:
                status = f'<span class="pill ok">signed in as {user}</span>' + (
                    ' <span class="pill">cookie arrived through the proxy</span>' if welcome else ""
                )
            else:
                status = (
                    '<span class="pill warn">not signed in</span> '
                    '<a class="btn small" href="/login">Sign in</a>'
                )
            html = html.replace("{{status}}", status)
        self._send(200, html.encode("utf-8"))

    do_HEAD = do_GET


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--port", type=int, default=3939)
    args = ap.parse_args()
    server = http.server.ThreadingHTTPServer(("127.0.0.1", args.port), Ledgerly)
    server.daemon_threads = True
    print(f"Ledgerly showcase on http://localhost:{args.port}  (sends X-Frame-Options: DENY)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
