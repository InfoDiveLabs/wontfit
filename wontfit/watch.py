"""Pluggable change detection for live reload.

A *detector* answers one question: "what does the thing I watch look like
right now?" as a short fingerprint string. The :class:`Watcher` polls a
detector (rate-limited, so ten harness tabs do not mean ten upstream hits
per tick), remembers the last fingerprint, and reports whether it changed.

Built-in strategies:

* :class:`UrlDetector` - fetch a URL through the proxy's upstream connection
  and hash the body. Works with any stack, no file access needed, but only
  notices changes that alter that one response.
* :class:`FileDetector` - glob local files and hash their mtimes and sizes.
  Notices any save, even ones that do not change the watched page.
* :class:`CompositeDetector` - any change in any child counts.

Writing your own: subclass :class:`ChangeDetector` and implement ``probe``.
"""

from __future__ import annotations

import glob
import hashlib
import http.client
import os
import threading
import time
from collections.abc import Sequence
from typing import Callable
from urllib.parse import urlsplit

from .proxy import ProxyConfig, build_upstream_headers


class ChangeDetector:
    """Base class. ``probe`` returns a fingerprint, or ``None`` when it cannot tell."""

    name = "none"

    def describe(self) -> str:
        """One human-readable line for the harness footer."""
        return self.name

    def probe(self) -> str | None:
        raise NotImplementedError


class NullDetector(ChangeDetector):
    """Live reload disabled."""

    name = "off"

    def describe(self) -> str:
        return "live reload off"

    def probe(self) -> str | None:
        return None


class UrlDetector(ChangeDetector):
    """Hash the body of one URL. ``fetch`` is injectable for tests."""

    name = "url"

    def __init__(self, url: str, fetch: Callable[[str], bytes]):
        self.url = url
        self._fetch = fetch

    def describe(self) -> str:
        return f"watching {self.url}"

    def probe(self) -> str | None:
        try:
            body = self._fetch(self.url)
        except Exception:
            return None
        return hashlib.sha1(body).hexdigest()[:12]


class FileDetector(ChangeDetector):
    """Hash mtime and size of every file matching the given globs (``**`` allowed)."""

    name = "files"

    def __init__(self, patterns: Sequence[str]):
        self.patterns = list(patterns)

    def files(self) -> list[str]:
        found: list[str] = []
        for pattern in self.patterns:
            found.extend(p for p in glob.glob(pattern, recursive=True) if os.path.isfile(p))
        return sorted(set(found))

    def describe(self) -> str:
        return f"watching {len(self.files())} file(s) matching {', '.join(self.patterns)}"

    def probe(self) -> str | None:
        digest = hashlib.sha1()
        for path in self.files():
            try:
                st = os.stat(path)
            except OSError:
                continue
            digest.update(f"{path}:{st.st_mtime_ns}:{st.st_size}\n".encode())
        return digest.hexdigest()[:12]


class CompositeDetector(ChangeDetector):
    """Combine detectors; a change in any child changes the fingerprint."""

    name = "composite"

    def __init__(self, children: Sequence[ChangeDetector]):
        self.children = list(children)

    def describe(self) -> str:
        return "; ".join(c.describe() for c in self.children)

    def probe(self) -> str | None:
        parts = [c.probe() for c in self.children]
        if all(p is None for p in parts):
            return None
        return "+".join(p or "-" for p in parts)


class Watcher:
    """Polls a detector no more often than ``min_interval`` and tracks the last change."""

    def __init__(self, detector: ChangeDetector, min_interval: float = 1.0):
        self.detector = detector
        self.min_interval = min_interval
        self._lock = threading.Lock()
        self._last_probe: float | None = None
        self._fingerprint: str | None = None
        self._changed_at: float | None = None
        self._changes = 0

    def status(self) -> dict[str, object]:
        """Probe if due, then report the current state as JSON-able data."""
        with self._lock:
            now = time.monotonic()
            if self._last_probe is None or now - self._last_probe >= self.min_interval:
                self._last_probe = now
                fresh = self.detector.probe()
                if fresh is not None and self._fingerprint is not None and fresh != self._fingerprint:
                    self._changed_at = time.time()
                    self._changes += 1
                if fresh is not None:
                    self._fingerprint = fresh
            return {
                "strategy": self.detector.name,
                "description": self.detector.describe(),
                "fingerprint": self._fingerprint,
                "changed_at": self._changed_at,
                "changes": self._changes,
                "reachable": self._fingerprint is not None,
            }


def fetch_via_upstream(config: ProxyConfig, url: str, limit: int = 8 * 1024 * 1024) -> bytes:
    """GET ``url`` (a path or absolute URL) from the upstream with the proxy's cookies and headers."""
    path = url
    if "://" in url:
        parts = urlsplit(url)
        path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
    headers = build_upstream_headers(config, [("Accept", "*/*"), ("Cache-Control", "no-cache")])
    conn = config.connect()
    try:
        conn.putrequest("GET", path, skip_host=True, skip_accept_encoding=True)
        for name, value in headers:
            conn.putheader(name, value)
        conn.endheaders()
        resp = conn.getresponse()
        if resp.status >= 500:
            raise http.client.HTTPException(f"upstream returned {resp.status}")
        return resp.read(limit)
    finally:
        conn.close()


def build_detector(config: ProxyConfig, watch_url: str | None, watch_files: Sequence[str]) -> ChangeDetector:
    """Choose the detector from CLI flags. Both flags given means both are watched."""
    children: list[ChangeDetector] = []
    if watch_url:
        children.append(UrlDetector(watch_url, lambda u: fetch_via_upstream(config, u)))
    if watch_files:
        children.append(FileDetector(watch_files))
    if not children:
        return NullDetector()
    if len(children) == 1:
        return children[0]
    return CompositeDetector(children)
