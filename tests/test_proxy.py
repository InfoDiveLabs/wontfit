"""Proxy header rewriting (pure functions) and an end-to-end round trip through real sockets."""

import gzip
import http.client
import http.server
import threading
import unittest

from wontfit.proxy import (
    ProxyConfig,
    ProxyServer,
    build_upstream_headers,
    filter_response_headers,
    rewrite_location,
    rewrite_origin_header,
    rewrite_set_cookie,
    strip_frame_ancestors,
)

CFG = ProxyConfig(upstream="http://localhost:3000", host="127.0.0.1", port=8081)


class StripFrameAncestorsTests(unittest.TestCase):
    def test_removes_only_frame_ancestors(self):
        csp = "default-src 'self'; frame-ancestors 'none'; script-src 'self' 'unsafe-inline'"
        self.assertEqual(strip_frame_ancestors(csp), "default-src 'self'; script-src 'self' 'unsafe-inline'")

    def test_case_insensitive_and_trailing_semicolon(self):
        self.assertEqual(strip_frame_ancestors("Frame-Ancestors 'self'; img-src *;"), "img-src *")

    def test_only_frame_ancestors_means_drop_header(self):
        self.assertIsNone(strip_frame_ancestors("frame-ancestors 'none'"))

    def test_does_not_touch_similar_names(self):
        self.assertEqual(strip_frame_ancestors("frame-src 'self'"), "frame-src 'self'")


class RewriteLocationTests(unittest.TestCase):
    def test_absolute_upstream_becomes_proxy(self):
        out = rewrite_location("http://localhost:3000/login?next=%2F#x", CFG.upstream, CFG.proxy_origin)
        self.assertEqual(out, "http://127.0.0.1:8081/login?next=%2F#x")

    def test_relative_untouched(self):
        self.assertEqual(rewrite_location("/login", CFG.upstream, CFG.proxy_origin), "/login")

    def test_other_origin_untouched(self):
        self.assertEqual(
            rewrite_location("https://example.com/", CFG.upstream, CFG.proxy_origin), "https://example.com/"
        )

    def test_default_port_equivalence(self):
        out = rewrite_location("http://localhost/", "http://localhost:80", CFG.proxy_origin)
        self.assertEqual(out, "http://127.0.0.1:8081/")

    def test_origin_header_rewritten_back(self):
        self.assertEqual(
            rewrite_origin_header("http://127.0.0.1:8081", CFG.upstream, CFG.proxy_origin),
            "http://localhost:3000",
        )
        self.assertEqual(
            rewrite_origin_header("http://127.0.0.1:8081/a?b=1", CFG.upstream, CFG.proxy_origin),
            "http://localhost:3000/a?b=1",
        )
        self.assertEqual(rewrite_origin_header("null", CFG.upstream, CFG.proxy_origin), "null")


class RewriteSetCookieTests(unittest.TestCase):
    def test_drops_domain_and_secure(self):
        out = rewrite_set_cookie("sid=abc; Path=/; Domain=app.local; Secure; HttpOnly; SameSite=Lax")
        self.assertEqual(out, "sid=abc; Path=/; HttpOnly; SameSite=Lax")

    def test_samesite_none_becomes_lax(self):
        self.assertEqual(rewrite_set_cookie("a=1; SameSite=None; Secure"), "a=1; SameSite=Lax")


class UpstreamHeaderTests(unittest.TestCase):
    def test_host_replaced_and_hop_by_hop_dropped(self):
        out = build_upstream_headers(
            CFG, [("Host", "127.0.0.1:8081"), ("Connection", "keep-alive"), ("Accept", "*/*")]
        )
        self.assertEqual(out[0], ("Host", "localhost:3000"))
        self.assertIn(("Accept", "*/*"), out)
        self.assertNotIn("Connection", [k for k, _ in out])

    def test_rewrite_host_modes(self):
        preserve = ProxyConfig(upstream="http://localhost:3000", rewrite_host="preserve")
        self.assertEqual(
            build_upstream_headers(preserve, [("Host", "127.0.0.1:8081")])[0], ("Host", "127.0.0.1:8081")
        )
        literal = ProxyConfig(upstream="http://localhost:3000", rewrite_host="app.test")
        self.assertEqual(build_upstream_headers(literal, [("Host", "x")])[0], ("Host", "app.test"))
        https_default = ProxyConfig(upstream="https://app.local")
        self.assertEqual(build_upstream_headers(https_default, [])[0], ("Host", "app.local"))

    def test_cookies_and_extra_headers_merged(self):
        cfg = ProxyConfig(
            upstream="http://localhost:3000", cookies=[("sid", "abc")], headers=[("X-Dev", "1")]
        )
        out = build_upstream_headers(cfg, [("Cookie", "theme=dark")])
        self.assertIn(("Cookie", "theme=dark; sid=abc"), out)
        self.assertIn(("X-Dev", "1"), out)

    def test_origin_and_referer_rewritten(self):
        out = build_upstream_headers(
            CFG, [("Origin", "http://127.0.0.1:8081"), ("Referer", "http://127.0.0.1:8081/x")]
        )
        self.assertIn(("Origin", "http://localhost:3000"), out)
        self.assertIn(("Referer", "http://localhost:3000/x"), out)


class ResponseHeaderTests(unittest.TestCase):
    def test_xfo_dropped_csp_trimmed_rest_kept(self):
        out = filter_response_headers(
            CFG,
            [
                ("X-Frame-Options", "DENY"),
                ("Content-Security-Policy", "default-src 'self'; frame-ancestors 'none'"),
                ("Content-Type", "text/html"),
                ("Content-Encoding", "gzip"),
                ("Transfer-Encoding", "chunked"),
                ("Content-Length", "10"),
                ("Location", "http://localhost:3000/next"),
                ("Set-Cookie", "a=1; Secure; Domain=localhost"),
                ("Set-Cookie", "b=2"),
            ],
        )
        names = [k.lower() for k, _ in out]
        self.assertNotIn("x-frame-options", names)
        self.assertNotIn("transfer-encoding", names)
        self.assertNotIn("content-length", names)
        self.assertIn(("Content-Security-Policy", "default-src 'self'"), out)
        self.assertIn(("Content-Encoding", "gzip"), out)
        self.assertIn(("Location", "http://127.0.0.1:8081/next"), out)
        self.assertEqual([v for k, v in out if k == "Set-Cookie"], ["a=1", "b=2"])

    def test_csp_with_only_frame_ancestors_is_removed(self):
        out = filter_response_headers(CFG, [("Content-Security-Policy", "frame-ancestors 'self'")])
        self.assertEqual(out, [])


# --- end to end ----------------------------------------------------------------------


class FakeUpstream(http.server.BaseHTTPRequestHandler):
    """A tiny app that blocks framing, redirects, sets cookies, gzips, and echoes."""

    protocol_version = "HTTP/1.1"
    seen = []

    def log_message(self, *a):
        pass

    def _send(self, status, body, extra=()):
        self.send_response(status)
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "default-src 'self'; frame-ancestors 'none'; img-src *")
        for k, v in extra:
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_GET(self):
        FakeUpstream.seen.append((self.command, self.path, dict(self.headers)))
        if self.path == "/redirect":
            self._send(302, b"", [("Location", f"http://{self.headers['Host']}/landed")])
        elif self.path == "/gz":
            self._send(
                200,
                gzip.compress(b"hello gzip"),
                [("Content-Encoding", "gzip"), ("Content-Type", "text/plain")],
            )
        elif self.path == "/chunky":
            self.send_response(200)
            self.send_header("Transfer-Encoding", "chunked")
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            for part in (b"one", b"two"):
                self.wfile.write(b"%x\r\n%s\r\n" % (len(part), part))
            self.wfile.write(b"0\r\n\r\n")
        else:
            self._send(
                200,
                b"<h1>hi</h1>",
                [("Content-Type", "text/html"), ("Set-Cookie", "sid=1; Secure; Domain=localhost")],
            )

    do_HEAD = do_GET

    def do_POST(self):
        FakeUpstream.seen.append((self.command, self.path, dict(self.headers)))
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self._send(201, b"echo:" + body, [("Content-Type", "text/plain")])


class EndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.upstream = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakeUpstream)
        cls.upstream.daemon_threads = True
        threading.Thread(target=cls.upstream.serve_forever, daemon=True).start()
        up_port = cls.upstream.server_address[1]
        cls.config = ProxyConfig(upstream=f"http://localhost:{up_port}", port=0, cookies=[("extra", "yes")])
        cls.proxy = ProxyServer(cls.config)
        cls.proxy.serve_in_thread()

    @classmethod
    def tearDownClass(cls):
        cls.proxy.shutdown()
        cls.proxy.server_close()
        cls.upstream.shutdown()
        cls.upstream.server_close()

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.config.port, timeout=5)
        conn.request(method, path, body=body, headers=headers or {})
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        return resp, data

    def test_frame_headers_removed_and_cookie_rewritten(self):
        resp, data = self.request("GET", "/", headers={"Cookie": "theme=dark"})
        self.assertEqual(resp.status, 200)
        self.assertEqual(data, b"<h1>hi</h1>")
        self.assertIsNone(resp.getheader("X-Frame-Options"))
        self.assertEqual(resp.getheader("Content-Security-Policy"), "default-src 'self'; img-src *")
        self.assertEqual(resp.getheader("Set-Cookie"), "sid=1")
        sent = FakeUpstream.seen[-1][2]
        self.assertEqual(sent["Cookie"], "theme=dark; extra=yes")
        self.assertEqual(sent["Host"], f"localhost:{self.upstream.server_address[1]}")

    def test_redirect_rewritten_to_proxy(self):
        resp, _ = self.request("GET", "/redirect")
        self.assertEqual(resp.status, 302)
        self.assertEqual(resp.getheader("Location"), f"http://127.0.0.1:{self.config.port}/landed")

    def test_post_body_forwarded(self):
        resp, data = self.request("POST", "/submit", body=b"a=1", headers={"Content-Type": "text/plain"})
        self.assertEqual(resp.status, 201)
        self.assertEqual(data, b"echo:a=1")

    def test_gzip_passes_through_untouched(self):
        resp, data = self.request("GET", "/gz", headers={"Accept-Encoding": "gzip"})
        self.assertEqual(resp.getheader("Content-Encoding"), "gzip")
        self.assertEqual(gzip.decompress(data), b"hello gzip")

    def test_chunked_upstream_is_streamed(self):
        resp, data = self.request("GET", "/chunky")
        self.assertEqual(data, b"onetwo")
        self.assertEqual(resp.getheader("Transfer-Encoding"), "chunked")

    def test_head_has_no_body(self):
        resp, data = self.request("HEAD", "/")
        self.assertEqual(resp.status, 200)
        self.assertEqual(data, b"")

    def test_unreachable_upstream_gives_502(self):
        dead = ProxyServer(ProxyConfig(upstream="http://127.0.0.1:1", port=0))
        dead.serve_in_thread()
        try:
            conn = http.client.HTTPConnection("127.0.0.1", dead.config.port, timeout=5)
            conn.request("GET", "/")
            resp = conn.getresponse()
            self.assertEqual(resp.status, 502)
            self.assertIn(b"unreachable", resp.read())
            conn.close()
        finally:
            dead.shutdown()
            dead.server_close()

    def test_websocket_upgrade_refused(self):
        resp, _ = self.request("GET", "/ws", headers={"Upgrade": "websocket", "Connection": "Upgrade"})
        self.assertEqual(resp.status, 501)


if __name__ == "__main__":
    unittest.main()
