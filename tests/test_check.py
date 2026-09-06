"""Report shaping, exit codes and the table for ``phoneframes check`` (no browser needed)."""

import argparse
import io
import unittest
from contextlib import redirect_stderr

from phoneframes.check import FrameResult, build_report, exit_code, failures, format_table, shape_result
from phoneframes.cli import parse_args, parse_fail_on
from phoneframes.shoot import contact_sheet_html, sheet_columns, sheet_viewport_width

RAW_BAD = {
    "overflow": {"amount": 385, "culprits": [{"label": "img.shot", "left": 20, "right": 780, "width": 760}]},
    "tapTargets": [{"label": "button.iconbtn", "width": 30, "height": 30}] * 5,
    "smallText": 2,
}
RAW_OK = {"overflow": None, "tapTargets": [], "smallText": 0}


class ShapeTests(unittest.TestCase):
    def test_shape_bad(self):
        r = shape_result("/", 375, 800, RAW_BAD)
        self.assertEqual((r.overflow_px, r.tap_targets, r.small_text), (385, 5, 2))
        self.assertEqual(r.culprits[0]["label"], "img.shot")
        self.assertEqual(r.failed_kinds, ["overflow", "taps", "text"])

    def test_shape_ok(self):
        r = shape_result("/terms", 393, 800, RAW_OK)
        self.assertEqual(r.failed_kinds, [])
        self.assertEqual(r.overflow_px, 0)


class ExitCodeTests(unittest.TestCase):
    def setUp(self):
        self.bad = shape_result("/", 375, 800, RAW_BAD)
        self.ok = shape_result("/terms", 375, 800, RAW_OK)
        self.err = FrameResult("/x", 375, 800, error="net::ERR_CONNECTION_REFUSED")

    def test_default_fails_only_on_overflow(self):
        self.assertEqual(exit_code([self.ok], ["overflow"]), 0)
        self.assertEqual(exit_code([self.bad], ["overflow"]), 1)
        taps_only = shape_result("/d", 375, 800, {"overflow": None, "tapTargets": [{}], "smallText": 0})
        self.assertEqual(exit_code([taps_only], ["overflow"]), 0)
        self.assertEqual(exit_code([taps_only], ["taps"]), 1)

    def test_none_selected_still_fails_on_errors(self):
        self.assertEqual(exit_code([self.bad], []), 0)
        self.assertEqual(exit_code([self.err], []), 1)

    def test_failure_lines(self):
        lines = failures([self.bad, self.err], ["overflow", "taps", "text"])
        self.assertEqual(
            lines,
            [
                "/ @ 375: overflow +385px (img.shot)",
                "/ @ 375: 5 tap target(s) under 44x44",
                "/ @ 375: 2 element(s) with text under 12px",
                "/x @ 375: error: net::ERR_CONNECTION_REFUSED",
            ],
        )

    def test_report_document(self):
        report = build_report("http://localhost:3939", [self.bad, self.ok], ["overflow"])
        self.assertFalse(report["ok"])
        self.assertEqual(report["fail_on"], ["overflow"])
        self.assertEqual(len(report["results"]), 2)
        self.assertEqual(report["results"][0]["culprits"][0]["label"], "img.shot")
        self.assertEqual(report["failures"], ["/ @ 375: overflow +385px (img.shot)"])


class TableTests(unittest.TestCase):
    def test_table_layout(self):
        table = format_table(
            [
                shape_result("/", 375, 800, RAW_BAD),
                shape_result("/terms", 393, 800, RAW_OK),
                FrameResult("/x", 375, 800, error="boom"),
            ]
        )
        lines = table.splitlines()
        self.assertTrue(lines[0].startswith("page"))
        self.assertTrue(set(lines[1]) <= {"-", " "})
        self.assertIn("+385px (img.shot)", lines[2])
        self.assertIn("fits", lines[3])
        self.assertIn("error", lines[4])


class FailOnParsingTests(unittest.TestCase):
    def test_values(self):
        self.assertEqual(parse_fail_on("overflow, TAPS"), ["overflow", "taps"])
        self.assertEqual(parse_fail_on("none"), [])
        with self.assertRaises(argparse.ArgumentTypeError):
            parse_fail_on("overflow,bogus")

    def test_check_parser(self):
        ns = parse_args(
            ["check", "--no-config", "--pages", "/,/a", "--fail-on", "taps,text", "--json", "r.json"]
        )
        self.assertEqual(ns.command, "check")
        self.assertEqual(ns.fail_on, ["taps", "text"])
        self.assertEqual(ns.json, "r.json")
        self.assertEqual(ns.settle, 0.5)
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parse_args(["check", "--no-config", "--fail-on", "everything"])


class ContactSheetTests(unittest.TestCase):
    def test_columns_and_width(self):
        self.assertEqual(sheet_columns(3), 3)
        self.assertEqual(sheet_columns(9), 4)
        self.assertEqual(sheet_columns(0), 1)
        self.assertEqual(sheet_viewport_width([375, 393, 430], 3), 375 + 393 + 430 + 24 * 2 + 28 * 2)
        self.assertEqual(
            sheet_viewport_width([375, 393, 430, 412, 344], 4), 430 + 412 + 393 + 375 + 24 * 3 + 28 * 2
        )

    def test_html_embeds_images_and_escapes(self):
        html = contact_sheet_html([("/a<b>", 375, 800, b"\x89PNG")], 1, "t<>")
        self.assertIn("data:image/png;base64,", html)
        self.assertIn("/a&lt;b&gt;", html)
        self.assertIn("t&lt;&gt;", html)
        self.assertIn("repeat(1,max-content)", html)


if __name__ == "__main__":
    unittest.main()
