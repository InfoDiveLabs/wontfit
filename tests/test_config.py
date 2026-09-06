"""Config file parsing, discovery, and merging with CLI flags."""

import os
import tempfile
import unittest
from pathlib import Path

from wontfit.cli import parse_args
from wontfit.config import (
    STARTER,
    ConfigError,
    extract_section,
    find_config,
    load_toml,
    parse_toml_subset,
    read_config_file,
    to_cli_defaults,
    write_starter,
)

SAMPLE = """
# a comment
upstream = "http://localhost:5173"   # trailing comment
port = 9000
pages = ["/", "/pricing",
         "/dashboard"]               # multi-line array
widths = ["se", 393, 430]
height = 700
watch_interval = 1.5
insecure = true
escaped = "say \\"hi\\" # not a comment"
literal = 'C:\\path'

[cookies]
session = "abc=def"

[headers]
"X-Dev" = "1"
"""


class SubsetParserTests(unittest.TestCase):
    def test_parses_sample(self):
        data = parse_toml_subset(SAMPLE)
        self.assertEqual(data["upstream"], "http://localhost:5173")
        self.assertEqual(data["port"], 9000)
        self.assertEqual(data["pages"], ["/", "/pricing", "/dashboard"])
        self.assertEqual(data["widths"], ["se", 393, 430])
        self.assertEqual(data["watch_interval"], 1.5)
        self.assertIs(data["insecure"], True)
        self.assertEqual(data["escaped"], 'say "hi" # not a comment')
        self.assertEqual(data["literal"], "C:\\path")
        self.assertEqual(data["cookies"], {"session": "abc=def"})
        self.assertEqual(data["headers"], {"X-Dev": "1"})

    def test_dotted_sections_nest(self):
        data = parse_toml_subset("[tool.wontfit]\nport = 1\n[tool.wontfit.cookies]\na = 'b'\n")
        self.assertEqual(data, {"tool": {"wontfit": {"port": 1, "cookies": {"a": "b"}}}})

    def test_errors_are_config_errors(self):
        with self.assertRaises(ConfigError):
            parse_toml_subset("port = ")
        with self.assertRaises(ConfigError):
            parse_toml_subset("this is not toml")
        with self.assertRaises(ConfigError):
            parse_toml_subset("pages = [\n'/'")

    def test_agrees_with_tomllib_when_available(self):
        try:
            import tomllib
        except ModuleNotFoundError:
            self.skipTest("tomllib needs Python 3.11+")
        self.assertEqual(parse_toml_subset(SAMPLE), tomllib.loads(SAMPLE))
        self.assertEqual(parse_toml_subset(STARTER), tomllib.loads(STARTER))

    def test_starter_parses_with_subset_parser(self):
        data = parse_toml_subset(STARTER)
        self.assertEqual(data["upstream"], "http://localhost:3000")
        self.assertEqual(data["widths"], ["se", "iphone15", "iphone15plus"])
        self.assertEqual(data["cookies"], {})
        to_cli_defaults(data)  # every starter key must be a known, valid key

    def test_extract_section(self):
        text = "[build-system]\nrequires = ['x']\n[tool.wontfit]\nport = 5\n[tool.other]\nport = 6\n"
        self.assertEqual(extract_section(text, "tool.wontfit").strip(), "port = 5")
        self.assertEqual(extract_section(text, "tool.missing"), "")


class DefaultsTests(unittest.TestCase):
    def test_translation(self):
        known_only = "\n".join(
            line for line in SAMPLE.splitlines() if not line.startswith(("escaped", "literal"))
        )
        out = to_cli_defaults(load_toml(known_only))
        self.assertEqual(out["upstream"], "http://localhost:5173")
        self.assertEqual(out["port"], 9000)
        self.assertEqual(out["widths"], [375, 393, 430])
        self.assertEqual(out["pages"], ["/", "/pricing", "/dashboard"])
        self.assertEqual(out["cookie"], [("session", "abc=def")])
        self.assertEqual(out["header"], [("X-Dev", "1")])
        self.assertEqual(out["watch_interval"], 1.5)
        self.assertIs(out["insecure"], True)

    def test_validation(self):
        with self.assertRaises(ConfigError):
            to_cli_defaults({"nope": 1})
        with self.assertRaises(ConfigError):
            to_cli_defaults({"widths": ["huge"]})
        with self.assertRaises(ConfigError):
            to_cli_defaults({"port": "8081"})
        with self.assertRaises(ConfigError):
            to_cli_defaults({"fail_on": ["overflow", "bogus"]})
        self.assertEqual(
            to_cli_defaults({"upstream": "localhost:8000/"})["upstream"], "http://localhost:8000"
        )
        self.assertEqual(to_cli_defaults({"pages": ["about"]})["pages"], ["/about"])


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()  # macOS: /var -> /private/var
        self.nested = self.root / "src" / "app"
        self.nested.mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_walks_upward_and_prefers_wontfit_toml(self):
        (self.root / "pyproject.toml").write_text("[tool.wontfit]\nport = 7000\n")
        found = find_config(self.nested)
        self.assertEqual(found[0], self.root / "pyproject.toml")
        self.assertEqual(found[1], {"port": 7000})
        (self.root / "wontfit.toml").write_text("port = 7001\n")
        self.assertEqual(find_config(self.nested)[1], {"port": 7001})

    def test_pyproject_without_section_is_skipped(self):
        (self.root / "pyproject.toml").write_text("[project]\nname = 'x'\n")
        self.assertIsNone(read_config_file(self.root / "pyproject.toml"))

    def test_pyproject_with_exotic_toml_elsewhere(self):
        text = (
            '[project]\nname = "x"\ndescription = """multi\nline"""\n'
            '[[project.authors]]\nname = "a"\n'
            '[tool.wontfit]\npages = ["/x"]\n'
        )
        (self.root / "pyproject.toml").write_text(text)
        self.assertEqual(read_config_file(self.root / "pyproject.toml"), {"pages": ["/x"]})

    def test_bad_file_reports_path(self):
        (self.root / "wontfit.toml").write_text("port = \n")
        with self.assertRaises(ConfigError) as ctx:
            find_config(self.nested)
        self.assertIn("wontfit.toml", str(ctx.exception))

    def test_no_config_found(self):
        self.assertIsNone(find_config(self.nested))

    def test_write_starter_refuses_overwrite(self):
        target = self.root / "wontfit.toml"
        write_starter(target, "http://localhost:4000")
        self.assertIn('upstream = "http://localhost:4000"', target.read_text())
        with self.assertRaises(FileExistsError):
            write_starter(target)


class CliMergeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()  # macOS: /var -> /private/var
        (self.root / "wontfit.toml").write_text(
            'upstream = "http://localhost:5173"\nport = 9000\npages = ["/", "/a"]\nwidths = [375]\n'
            'watch_files = ["src/**"]\nfail_on = ["overflow", "taps"]\nout = "pics"\n[cookies]\nsid = "1"\n'
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_config_supplies_defaults(self):
        ns = parse_args([], config_dir=self.root)
        self.assertEqual(ns.config_path, self.root / "wontfit.toml")
        self.assertEqual(ns.upstream, "http://localhost:5173")
        self.assertEqual(ns.port, 9000)
        self.assertEqual(ns.pages, ["/", "/a"])
        self.assertEqual(ns.widths, [375])
        self.assertEqual(ns.watch_file, ["src/**"])
        self.assertIsNone(ns.watch_url)  # files configured, so no URL default is added
        self.assertEqual(ns.cookie, [("sid", "1")])

    def test_flags_override_and_append(self):
        ns = parse_args(["--port", "1", "--pages", "/z", "--cookie", "extra=2"], config_dir=self.root)
        self.assertEqual(ns.port, 1)
        self.assertEqual(ns.pages, ["/z"])
        self.assertEqual(ns.cookie, [("sid", "1"), ("extra", "2")])

    def test_subcommands_take_their_keys(self):
        check = parse_args(["check"], config_dir=self.root)
        self.assertEqual(check.fail_on, ["overflow", "taps"])
        self.assertEqual(check.pages, ["/", "/a"])
        shoot = parse_args(["shoot"], config_dir=self.root)
        self.assertEqual(shoot.out, "pics")
        self.assertFalse(hasattr(shoot, "port"))

    def test_no_config_flag(self):
        ns = parse_args(["--no-config"], config_dir=self.root)
        self.assertIsNone(ns.config_path)
        self.assertEqual(ns.port, 8081)

    def test_init_ignores_config(self):
        ns = parse_args(["init", "--upstream", "localhost:1234"], config_dir=self.root)
        self.assertEqual(ns.command, "init")
        self.assertEqual(ns.upstream, "http://localhost:1234")

    def test_cwd_discovery(self):
        old = os.getcwd()
        os.chdir(self.root)
        try:
            self.assertEqual(parse_args([]).port, 9000)
        finally:
            os.chdir(old)


if __name__ == "__main__":
    unittest.main()
