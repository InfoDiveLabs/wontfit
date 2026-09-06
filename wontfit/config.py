"""Project configuration: ``wontfit.toml`` or ``[tool.wontfit]`` in ``pyproject.toml``.

The file is discovered from the current directory upward, so ``wontfit``
run anywhere inside a project picks it up. Values become argparse *defaults*,
so any flag on the command line still wins.

Python 3.11+ parses TOML with :mod:`tomllib`. Older interpreters use
:func:`parse_toml_subset`, which understands the subset a wontfit config
needs: comments, ``[sections]``, strings, numbers, booleans and arrays. For
``pyproject.toml`` only the ``[tool.wontfit]`` block is fed to it, so the
rest of that file may use any TOML it likes.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from . import CHECK_KINDS, PRESETS

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - depends on interpreter
    tomllib = None  # type: ignore[assignment]

FILE_NAME = "wontfit.toml"
PYPROJECT = "pyproject.toml"
SECTION = "tool.wontfit"

#: Accepted keys and the argparse destination each maps to.
KEYS = {
    "upstream": "upstream",
    "port": "port",
    "pages": "pages",
    "widths": "widths",
    "height": "height",
    "cookies": "cookie",
    "headers": "header",
    "watch_url": "watch_url",
    "watch_files": "watch_file",
    "watch_interval": "watch_interval",
    "rewrite_host": "rewrite_host",
    "insecure": "insecure",
    "out": "out",
    "fail_on": "fail_on",
}

STARTER = """# wontfit configuration. Commit this so contributors can just run `wontfit`.
# Every key is optional; command-line flags override anything set here.

# The app to preview.
upstream = "http://localhost:3000"

# Port for the proxy and harness (always bound to 127.0.0.1).
port = 8081

# Pages to open, one column each.
pages = ["/"]

# CSS widths: numbers or preset names
# (se, iphone15, iphone15plus, pixel8, fold, ipadmini, ipad, laptop).
widths = ["se", "iphone15", "iphone15plus"]

# Frame height in CSS px.
height = 800

# Live reload: poll this URL (default: the first page) and/or watch local files.
# watch_url = "/"
# watch_files = ["src/**/*.css", "templates/**/*.html"]
watch_interval = 2

# Host header sent upstream: omit for the upstream's own host, "preserve" for the browser's.
# rewrite_host = "preserve"

# Accept self-signed certificates on an HTTPS upstream.
insecure = false

# Where `wontfit shoot` writes PNGs.
out = "shots"

# Which `wontfit check` findings fail the build: any of overflow, taps, text.
fail_on = ["overflow"]

# Cookies and headers sent with every upstream request.
[cookies]
# session = "paste-a-dev-session-here"

[headers]
# Authorization = "Bearer dev-token"
"""


class ConfigError(ValueError):
    """The config file exists but cannot be used."""


# --- TOML subset -----------------------------------------------------------------------

_KEY = r'(?:[A-Za-z0-9_-]+|"[^"]*")'
_LINE = re.compile(rf"^\s*({_KEY}(?:\s*\.\s*{_KEY})*)\s*=\s*(.*?)\s*$")
_SECTION = re.compile(rf"^\s*\[\s*({_KEY}(?:\s*\.\s*{_KEY})*)\s*\]\s*(?:#.*)?$")


def _strip_comment(text: str) -> str:
    """Drop a trailing ``# comment`` that is not inside a string."""
    out = []
    quote: str | None = None
    i = 0
    while i < len(text):
        ch = text[i]
        if quote:
            out.append(ch)
            if ch == "\\" and quote == '"' and i + 1 < len(text):
                out.append(text[i + 1])
                i += 1
            elif ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
            out.append(ch)
        elif ch == "#":
            break
        else:
            out.append(ch)
        i += 1
    return "".join(out).strip()


def _unquote_key(key: str) -> str:
    key = key.strip()
    return key[1:-1] if key.startswith('"') else key


def _parse_scalar(text: str, line_no: int) -> Any:
    text = text.strip()
    if text.startswith('"') and text.endswith('"') and len(text) >= 2:
        return bytes(text[1:-1], "utf-8").decode("unicode_escape")
    if text.startswith("'") and text.endswith("'") and len(text) >= 2:
        return text[1:-1]
    if text == "true":
        return True
    if text == "false":
        return False
    if re.fullmatch(r"[+-]?\d[\d_]*", text):
        return int(text.replace("_", ""))
    if re.fullmatch(r"[+-]?(\d[\d_]*)?\.\d[\d_]*([eE][+-]?\d+)?|[+-]?\d[\d_]*[eE][+-]?\d+", text):
        return float(text.replace("_", ""))
    raise ConfigError(
        f"line {line_no}: cannot parse value {text!r} (strings, numbers, booleans, arrays only)"
    )


def _split_array(inner: str, line_no: int) -> list[Any]:
    items: list[Any] = []
    current: list[str] = []
    quote: str | None = None
    for ch in inner:
        if quote:
            current.append(ch)
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
            current.append(ch)
        elif ch == ",":
            piece = "".join(current).strip()
            if piece:
                items.append(_parse_scalar(piece, line_no))
            current = []
        else:
            current.append(ch)
    tail = "".join(current).strip()
    if tail:
        items.append(_parse_scalar(tail, line_no))
    return items


def parse_toml_subset(text: str) -> dict[str, Any]:
    """Parse the TOML subset wontfit uses. Sections nest by dotted name."""
    root: dict[str, Any] = {}
    table = root
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        raw = lines[i]
        line = _strip_comment(raw)
        i += 1
        if not line:
            continue
        section = _SECTION.match(line)
        if section:
            table = root
            for part in re.split(r"\s*\.\s*", section.group(1)):
                table = table.setdefault(_unquote_key(part), {})
            continue
        match = _LINE.match(line)
        if not match:
            raise ConfigError(f"line {i}: expected key = value, got {raw.strip()!r}")
        key, value = _unquote_key(match.group(1)), match.group(2)
        if value.startswith("["):
            start = i
            while value.count("[") > value.count("]") or not value.rstrip().endswith("]"):
                if i >= len(lines):
                    raise ConfigError(f"line {start}: unterminated array")
                value += " " + _strip_comment(lines[i])
                i += 1
            table[key] = _split_array(value.strip()[1:-1], start)
        else:
            table[key] = _parse_scalar(value, i)
    return root


def load_toml(text: str) -> dict[str, Any]:
    """Full TOML when :mod:`tomllib` exists, the subset parser otherwise."""
    if tomllib is not None:
        try:
            return tomllib.loads(text)
        except tomllib.TOMLDecodeError as exc:
            raise ConfigError(str(exc)) from None
    return parse_toml_subset(text)


def extract_section(text: str, section: str) -> str:
    """Return just the lines of ``[section]`` (used for pyproject.toml on old Pythons)."""
    out: list[str] = []
    inside = False
    for line in text.splitlines():
        header = _SECTION.match(_strip_comment(line))
        if header:
            name = ".".join(_unquote_key(p) for p in re.split(r"\s*\.\s*", header.group(1)))
            inside = name == section
            continue
        if inside:
            out.append(line)
    return "\n".join(out)


# --- discovery ---------------------------------------------------------------------------


def read_config_file(path: Path) -> dict[str, Any] | None:
    """Load the wontfit table from one file, or ``None`` if the file has none."""
    text = path.read_text(encoding="utf-8")
    if path.name == PYPROJECT:
        if tomllib is not None:
            data = load_toml(text)
            for part in SECTION.split("."):
                data = data.get(part) if isinstance(data, dict) else None
                if data is None:
                    return None
            return dict(data)
        body = extract_section(text, SECTION)
        return parse_toml_subset(body) if body.strip() else None
    return load_toml(text)


def find_config(start: Path | None = None) -> tuple[Path, dict[str, Any]] | None:
    """Walk from ``start`` (default cwd) upward; ``wontfit.toml`` beats ``pyproject.toml``."""
    here = (start or Path.cwd()).resolve()
    for directory in (here, *here.parents):
        for name in (FILE_NAME, PYPROJECT):
            candidate = directory / name
            if candidate.is_file():
                try:
                    data = read_config_file(candidate)
                except ConfigError as exc:
                    raise ConfigError(f"{candidate}: {exc}") from None
                if data is not None:
                    return candidate, data
    return None


# --- merging -------------------------------------------------------------------------------


def _widths(value: Any) -> list[int]:
    if not isinstance(value, list):
        raise ConfigError("widths must be an array")
    out = []
    for item in value:
        token = str(item).strip().lower()
        if token in PRESETS:
            out.append(PRESETS[token][1])
        elif isinstance(item, int) and 100 <= item <= 4000:
            out.append(item)
        else:
            raise ConfigError(f"widths: {item!r} is not a number in 100..4000 or a preset name")
    return out


def _pages(value: Any) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(p, str) for p in value):
        raise ConfigError("pages must be an array of strings")
    return [p if p.startswith("/") else "/" + p for p in value if p.strip()]


def _pairs(value: Any, name: str) -> list[tuple[str, str]]:
    if not isinstance(value, dict):
        raise ConfigError(f"{name} must be a table of name = value")
    return [(str(k), str(v)) for k, v in value.items()]


def to_cli_defaults(data: dict[str, Any]) -> dict[str, Any]:
    """Validate a config table and translate it to argparse destination names."""
    unknown = sorted(set(data) - set(KEYS))
    if unknown:
        raise ConfigError(f"unknown key(s): {', '.join(unknown)}; known: {', '.join(KEYS)}")
    out: dict[str, Any] = {}
    for key, value in data.items():
        dest = KEYS[key]
        if key == "widths":
            out[dest] = _widths(value)
        elif key == "pages":
            out[dest] = _pages(value)
        elif key in ("cookies", "headers"):
            out[dest] = _pairs(value, key)
        elif key == "watch_files":
            if not isinstance(value, list):
                raise ConfigError("watch_files must be an array")
            out[dest] = [str(v) for v in value]
        elif key == "fail_on":
            if not isinstance(value, list):
                raise ConfigError("fail_on must be an array")
            kinds = [str(v).lower() for v in value]
            bad = [k for k in kinds if k not in CHECK_KINDS]
            if bad:
                raise ConfigError(f"fail_on: unknown {', '.join(bad)}; choose from {', '.join(CHECK_KINDS)}")
            out[dest] = kinds
        elif key == "upstream":
            url = str(value).strip()
            out[dest] = (url if "://" in url else "http://" + url).rstrip("/")
        elif key in ("port", "height"):
            if not isinstance(value, int) or isinstance(value, bool):
                raise ConfigError(f"{key} must be an integer")
            out[dest] = value
        elif key == "watch_interval":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ConfigError("watch_interval must be a number")
            out[dest] = float(value)
        elif key == "insecure":
            if not isinstance(value, bool):
                raise ConfigError("insecure must be true or false")
            out[dest] = value
        else:
            out[dest] = str(value)
    return out


def write_starter(path: Path, upstream: str | None = None) -> None:
    """Write the commented starter config. Refuses to overwrite."""
    if path.exists():
        raise FileExistsError(str(path))
    text = STARTER
    if upstream:
        text = text.replace('upstream = "http://localhost:3000"', f'upstream = "{upstream}"')
    path.write_text(text, encoding="utf-8")
