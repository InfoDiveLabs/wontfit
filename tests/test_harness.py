"""Harness state serialisation, page rendering, and the harness HTTP routes."""

import http.client
import json
import unittest

from wontfit import HARNESS_PATH
from wontfit.harness import HarnessState, harness_config, make_route, render_harness
from wontfit.proxy import ProxyConfig, ProxyServer
from wontfit.watch import NullDetector, Watcher


class HarnessStateTests(unittest.TestCase):
    def test_round_trip(self):
        state = HarnessState(
            pages=["/", "/about?x=1"], widths=[375, 820], height=900, landscape=True, live=False
        )
        query = state.to_query()
        self.assertEqual(query, "p=/,/about%3Fx%3D1&w=375,820&h=900&o=l&live=0")
        self.assertEqual(HarnessState.from_query(query), state)

    def test_defaults_omitted_from_query(self):
        self.assertEqual(HarnessState().to_query(), "p=/&w=375,393,430&h=800")

    def test_from_query_tolerates_garbage(self):
        default = HarnessState(pages=["/x"], widths=[400], height=700)
        parsed = HarnessState.from_query("?p=&w=abc,10,se&h=99999&o=p", default=default)
        self.assertEqual(parsed.pages, ["/x"])
        self.assertEqual(parsed.widths, [375])  # 'se' preset survives, junk dropped
        self.assertEqual(parsed.height, 700)
        self.assertFalse(parsed.landscape)
        self.assertTrue(parsed.live)

    def test_pages_get_leading_slash(self):
        self.assertEqual(HarnessState.from_query("p=about,/x").pages, ["/about", "/x"])

    def test_url_and_frames(self):
        state = HarnessState(pages=["/"], widths=[375, 430], height=800, landscape=True)
        self.assertEqual(
            state.url("http://127.0.0.1:8081/"), "http://127.0.0.1:8081/__wontfit?p=/&w=375,430&h=800&o=l"
        )
        self.assertEqual(
            state.frames(),
            [
                {"page": "/", "width": 800, "height": 375, "device": 375},
                {"page": "/", "width": 800, "height": 430, "device": 430},
            ],
        )


class RenderTests(unittest.TestCase):
    def test_render_inlines_config_and_diagnostics(self):
        html = render_harness(HarnessState(pages=["/a"], widths=[393]), 2.5, "watching /a")
        self.assertIn("WontfitDiagnostics", html)
        self.assertNotIn("/*__WONTFIT_", html)
        start = html.index("var CONFIG = ") + len("var CONFIG = ")
        end = html.index(";", start)
        config = json.loads(html[start:end])
        self.assertEqual(config["pages"], ["/a"])
        self.assertEqual(config["widths"], [393])
        self.assertEqual(config["watch"], {"interval": 2.5, "description": "watching /a"})
        self.assertTrue(any(p["name"] == "Galaxy Fold" and p["width"] == 344 for p in config["presets"]))

    def test_config_escapes_script_close(self):
        cfg = harness_config(HarnessState(pages=["/</script>"]), 2, "")
        rendered = render_harness(HarnessState(pages=["/</script>"]), 2, "")
        self.assertEqual(cfg["pages"], ["/</script>"])
        self.assertNotIn("/</script>", rendered)


class RouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = ProxyConfig(upstream="http://127.0.0.1:1", port=0)
        route = make_route(HarnessState(), Watcher(NullDetector()), 2.0)
        cls.server = ProxyServer(cls.config, route)
        cls.server.serve_in_thread()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def get(self, path):
        conn = http.client.HTTPConnection("127.0.0.1", self.config.port, timeout=5)
        conn.request("GET", path)
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        return resp, body

    def test_harness_served(self):
        resp, body = self.get(HARNESS_PATH + "?p=/&w=375")
        self.assertEqual(resp.status, 200)
        self.assertIn("text/html", resp.getheader("Content-Type"))
        self.assertIn(b"<title>wontfit</title>", body)

    def test_watch_endpoint(self):
        resp, body = self.get(HARNESS_PATH + "/watch")
        self.assertEqual(resp.status, 200)
        self.assertEqual(json.loads(body)["strategy"], "off")

    def test_unknown_harness_route(self):
        resp, _ = self.get(HARNESS_PATH + "/nope")
        self.assertEqual(resp.status, 404)

    def test_other_paths_go_to_upstream(self):
        resp, body = self.get("/__wontfitish")
        self.assertEqual(resp.status, 502)
        self.assertIn(b"unreachable", body)


if __name__ == "__main__":
    unittest.main()
