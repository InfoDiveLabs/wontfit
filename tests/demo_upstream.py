#!/usr/bin/env python3
"""A throwaway upstream that refuses to be framed, for trying wontfit out.

    python3 tests/demo_upstream.py --port 3999
    wontfit --upstream http://localhost:3999 --pages /,/wide --open

Every response carries ``X-Frame-Options: DENY`` and a CSP with
``frame-ancestors 'none'`` so you can watch the proxy strip them. ``/wide``
overflows on phones on purpose, ``/login`` redirects with an absolute
Location, and ``/whoami`` echoes the headers it received.
"""

import argparse
import http.server
import json

PAGE = """<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>
 body{{font:16px system-ui;margin:0;padding:16px}} nav a{{margin-right:8px;font-size:11px}}
 .hero{{background:#eef;padding:24px;border-radius:12px}} button{{padding:2px 6px;font-size:12px}}
 .wide{{width:900px;height:40px;background:repeating-linear-gradient(90deg,#f66 0 20px,#fcc 20px 40px)}}
 small{{font-size:10px;color:#666}}
</style>
<nav><a href="/">home</a><a href="/wide">wide</a><a href="/login">login</a><a href="/whoami">whoami</a></nav>
<div class=hero><h1>{title}</h1><p>Served with X-Frame-Options: DENY and CSP frame-ancestors 'none'.</p>
<button>tiny</button> <small>this text is 10px</small></div>
{extra}
"""


class Demo(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, status, body, ctype="text/html; charset=utf-8", extra=()):
        data = body.encode()
        self.send_response(status)
        self.send_header("X-Frame-Options", "DENY")
        self.send_header(
            "Content-Security-Policy", "default-src 'self' 'unsafe-inline'; frame-ancestors 'none'; img-src *"
        )
        self.send_header("Content-Type", ctype)
        for k, v in extra:
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/wide":
            self._send(200, PAGE.format(title="Wide", extra='<div class="wide card"></div>'))
        elif path == "/login":
            self._send(
                302,
                "",
                extra=[
                    ("Location", f"http://{self.headers['Host']}/?logged=in"),
                    ("Set-Cookie", "demo=1; Path=/; Secure; Domain=localhost"),
                ],
            )
        elif path == "/whoami":
            self._send(200, json.dumps(dict(self.headers), indent=2), "application/json")
        else:
            self._send(200, PAGE.format(title="Demo app", extra="<p>Resize-friendly page.</p>"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=3999)
    args = ap.parse_args()
    server = http.server.ThreadingHTTPServer(("127.0.0.1", args.port), Demo)
    print(f"demo upstream on http://localhost:{args.port} (blocks framing)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
