"""CLI argument parsing and the config it produces."""

import argparse
import io
import unittest
from contextlib import redirect_stderr
from pathlib import Path

from wontfit import PRESETS
from wontfit.cli import (
    config_from_args,
    parse_args,
    parse_cookie,
    parse_header,
    parse_pages,
    parse_widths,
)
from wontfit.shoot import planned_files, slug_for


class ValueParserTests(unittest.TestCase):
    def test_cookie(self):
        self.assertEqual(parse_cookie("sid=abc=def"), ("sid", "abc=def"))
        with self.assertRaises(argparse.ArgumentTypeError):
            parse_cookie("nonsense")

    def test_header(self):
        self.assertEqual(parse_header("Authorization: Bearer x:y"), ("Authorization", "Bearer x:y"))
        with self.assertRaises(argparse.ArgumentTypeError):
            parse_header("NoColon")

    def test_pages_get_leading_slash(self):
        self.assertEqual(parse_pages("/, about ,,/x?y=1"), ["/", "/about", "/x?y=1"])
        with self.assertRaises(argparse.ArgumentTypeError):
            parse_pages(" , ")

    def test_widths_accept_numbers_and_presets(self):
        self.assertEqual(parse_widths("375, se, Pixel8"), [375, PRESETS["se"][1], PRESETS["pixel8"][1]])
        with self.assertRaises(argparse.ArgumentTypeError):
            parse_widths("huge")
        with self.assertRaises(argparse.ArgumentTypeError):
            parse_widths("50")


class ParseArgsTests(unittest.TestCase):
    def test_defaults(self):
        ns = parse_args([])
        self.assertEqual(ns.command, "serve")
        self.assertEqual(ns.upstream, "http://localhost:3000")
        self.assertEqual(ns.port, 8081)
        self.assertEqual(ns.pages, ["/"])
        self.assertEqual(ns.widths, [375, 393, 430])
        self.assertEqual(ns.watch_url, "/")  # defaults to the first page
        self.assertEqual(ns.watch_interval, 2.0)
        self.assertFalse(ns.open)

    def test_full_serve_invocation(self):
        ns = parse_args(
            [
                "--upstream",
                "https://localhost:5173/",
                "--port",
                "9000",
                "--open",
                "--cookie",
                "a=1",
                "--cookie",
                "b=2",
                "--header",
                "X-Dev: yes",
                "--pages",
                "/,/about",
                "--widths",
                "375,ipad",
                "--insecure",
                "--rewrite-host",
                "preserve",
                "--watch-file",
                "src/**/*.css",
                "--watch-interval",
                "0.5",
            ]
        )
        self.assertEqual(ns.upstream, "https://localhost:5173")
        self.assertEqual(ns.port, 9000)
        self.assertTrue(ns.open)
        self.assertEqual(ns.cookie, [("a", "1"), ("b", "2")])
        self.assertEqual(ns.header, [("X-Dev", "yes")])
        self.assertEqual(ns.pages, ["/", "/about"])
        self.assertEqual(ns.widths, [375, 820])
        self.assertTrue(ns.insecure)
        self.assertEqual(ns.rewrite_host, "preserve")
        self.assertEqual(ns.watch_file, ["src/**/*.css"])
        self.assertIsNone(ns.watch_url)  # --watch-file alone does not add the URL default
        self.assertEqual(ns.watch_interval, 0.5)

    def test_no_watch_clears_both(self):
        ns = parse_args(["--no-watch", "--watch-file", "x"])
        self.assertIsNone(ns.watch_url)
        self.assertEqual(ns.watch_file, [])

    def test_upstream_without_scheme(self):
        self.assertEqual(parse_args(["--upstream", "localhost:8080"]).upstream, "http://localhost:8080")

    def test_shoot_subcommand(self):
        ns = parse_args(["shoot", "--pages", "/,/pricing", "--widths", "se", "--out", "pics", "--full-page"])
        self.assertEqual(ns.command, "shoot")
        self.assertEqual(ns.pages, ["/", "/pricing"])
        self.assertEqual(ns.widths, [375])
        self.assertEqual(ns.out, "pics")
        self.assertTrue(ns.full_page)

    def test_bad_value_exits(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parse_args(["--widths", "banana"])

    def test_config_from_args(self):
        cfg = config_from_args(
            parse_args(["--upstream", "https://app.local", "--cookie", "s=1", "--insecure", "-v"])
        )
        self.assertEqual(cfg.upstream, "https://app.local")
        self.assertEqual(cfg.cookies, [("s", "1")])
        self.assertTrue(cfg.insecure)
        self.assertTrue(cfg.verbose)
        self.assertTrue(cfg.upstream_is_tls)
        self.assertEqual(cfg.proxy_origin, "http://127.0.0.1:8081")


class ShootPlanningTests(unittest.TestCase):
    def test_slugs(self):
        self.assertEqual(slug_for("/"), "index")
        self.assertEqual(slug_for("/about/team?x=1#frag"), "about-team")

    def test_planned_files(self):
        files = planned_files(["/", "/a"], [375, 820], 800, False, Path("shots"))
        self.assertEqual(
            [f.name for f in files],
            ["index-375x800.png", "index-820x800.png", "a-375x800.png", "a-820x800.png"],
        )
        landscape = planned_files(["/"], [375], 800, True, Path("shots"))
        self.assertEqual(landscape[0].name, "index-800x375.png")


if __name__ == "__main__":
    unittest.main()
