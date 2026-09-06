"""Change detectors and the rate-limited watcher."""

import os
import tempfile
import unittest

from phoneframes.proxy import ProxyConfig
from phoneframes.watch import (
    CompositeDetector,
    FileDetector,
    NullDetector,
    UrlDetector,
    Watcher,
    build_detector,
)


class UrlDetectorTests(unittest.TestCase):
    def test_fingerprint_follows_body(self):
        bodies = {"n": 0}

        def fetch(url):
            return f"body {bodies['n']}".encode()

        det = UrlDetector("/", fetch)
        first = det.probe()
        self.assertEqual(det.probe(), first)
        bodies["n"] = 1
        self.assertNotEqual(det.probe(), first)
        self.assertEqual(det.describe(), "watching /")

    def test_fetch_failure_is_none(self):
        def boom(url):
            raise OSError("down")

        self.assertIsNone(UrlDetector("/", boom).probe())


class FileDetectorTests(unittest.TestCase):
    def test_mtime_and_size_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "a.css")
            with open(path, "w") as fh:
                fh.write("a{}")
            det = FileDetector([os.path.join(tmp, "**", "*.css")])
            self.assertEqual(det.files(), [path])
            before = det.probe()
            with open(path, "w") as fh:
                fh.write("a{color:red}")
            os.utime(path, (1, 1))  # deterministic mtime change regardless of clock granularity
            self.assertNotEqual(det.probe(), before)
            self.assertIn("1 file(s)", det.describe())

    def test_no_files_is_stable_fingerprint(self):
        det = FileDetector(["/nonexistent/**/*.zzz"])
        self.assertEqual(det.probe(), det.probe())


class WatcherTests(unittest.TestCase):
    def test_counts_changes_and_rate_limits(self):
        values = ["a"]

        class Det(NullDetector):
            name = "test"

            def probe(self):
                return values[0]

        watcher = Watcher(Det(), min_interval=1000)
        first = watcher.status()
        self.assertEqual(first["fingerprint"], "a")
        self.assertEqual(first["changes"], 0)
        self.assertTrue(first["reachable"])
        values[0] = "b"
        self.assertEqual(watcher.status()["fingerprint"], "a")  # rate-limited: no re-probe yet
        watcher._last_probe = None  # force the next status() to probe again
        second = watcher.status()
        self.assertEqual(second["fingerprint"], "b")
        self.assertEqual(second["changes"], 1)
        self.assertIsNotNone(second["changed_at"])

    def test_unreachable_keeps_last_fingerprint(self):
        values = ["a"]

        class Det(NullDetector):
            def probe(self):
                return values[0]

        watcher = Watcher(Det(), min_interval=0)
        watcher.status()
        values[0] = None
        st = watcher.status()
        self.assertEqual(st["fingerprint"], "a")
        self.assertEqual(st["changes"], 0)


class BuildDetectorTests(unittest.TestCase):
    def test_selection(self):
        cfg = ProxyConfig()
        self.assertIsInstance(build_detector(cfg, None, []), NullDetector)
        self.assertIsInstance(build_detector(cfg, "/", []), UrlDetector)
        self.assertIsInstance(build_detector(cfg, None, ["*.css"]), FileDetector)
        both = build_detector(cfg, "/", ["*.css"])
        self.assertIsInstance(both, CompositeDetector)
        self.assertEqual([c.name for c in both.children], ["url", "files"])


if __name__ == "__main__":
    unittest.main()
