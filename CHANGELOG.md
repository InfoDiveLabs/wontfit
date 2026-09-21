# Changelog

All notable changes to wontfit are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.2.1] - 2026-09-21

### Changed
- **Published to PyPI.** `pipx install wontfit` and `uvx wontfit` now work;
  install instructions, the CI example and the Playwright hint use the
  PyPI name again. Tag pushes publish to PyPI through Trusted Publishing,
  then create the GitHub release with the same files.
- README links and images are absolute, so they render on PyPI as well as
  GitHub.

## [0.2.0] - 2026-09-21

First public release. 0.1.0 was never tagged or published; its entry is kept
as the record of what the first cut contained.

### Added
- `wontfit.toml` / `[tool.wontfit]` in `pyproject.toml`, discovered from
  the current directory upward; flags override. `wontfit init` writes a
  commented starter. `--no-config` ignores any file. A built-in TOML-subset
  parser covers Python 3.9 and 3.10; 3.11+ uses `tomllib`.
- `wontfit check`: the same diagnostics headlessly via Playwright, a
  terminal table, `--json` report, and `--fail-on overflow,taps,text` for CI.
- `wontfit shoot` now also writes `contact-sheet.png` (all frames tiled),
  reads the config file, and accepts `--landscape`, `--timeout`, `--settle`.
- `examples/showcase`: the Ledgerly demo site (marketing pages plus a dashboard)
  that blocks framing and has six planted mobile bugs; `make showcase`.
- Real screenshots in `docs/images` with `docs/screenshots.py` to regenerate them,
  `docs/recipes.md` for twelve stacks, `docs/ci-example.yml` and a pre-push hook example.

### Changed
- **Moved to [InfoDiveLabs/wontfit](https://github.com/InfoDiveLabs/wontfit) and
  made public.** Install from a release tag
  (`pipx install git+https://github.com/InfoDiveLabs/wontfit@v0.2.0`) or the
  wheel attached to the GitHub release; the package is not on PyPI.
- The Playwright install hint no longer suggests `pip install 'wontfit[shoot]'`,
  which cannot resolve while the package is not on PyPI.
- **Renamed the project from `phoneframes` to `wontfit`,** before any release.
  The package, module and console script are `wontfit`; the harness moved from
  `/__phoneframes` to `/__wontfit`; config lives in `wontfit.toml` or
  `[tool.wontfit]`. Nothing had been published under the old name, so there is
  no compatibility shim.
- Overflow diagnostics list only the outermost offending elements, so a wide
  table no longer reports every `thead`, `tr` and `th` inside it.
- Frame captions wrap within the frame width instead of widening the column.

## [0.1.0] - 2026-09-06

### Added
- Reverse proxy on `127.0.0.1` that strips `X-Frame-Options` and the
  `frame-ancestors` directive from `Content-Security-Policy` (keeping the rest),
  rewrites absolute `Location` headers back to the proxy, forwards cookies both
  ways (dropping `Domain`/`Secure` so they stick on the loopback origin), streams
  bodies, passes `Content-Encoding` through untouched, and supports HTTPS
  upstreams with `--insecure` for self-signed certificates.
- `--rewrite-host` to control the upstream `Host` header (`preserve` or a literal).
- Harness at `/__wontfit`: pages, typed widths or device presets (iPhone SE,
  iPhone 15, iPhone 15 Plus, Pixel 8, Galaxy Fold, iPad Mini, iPad, laptop),
  height, orientation toggle, one column per page x width, state in the URL,
  "Reload frames" with the `r` shortcut.
- Per-frame diagnostics: horizontal overflow with culprit elements, tap targets
  under 44x44 CSS px with a toggleable overlay, text under 12px, and cross-frame
  inspect highlighting. All best-effort and safe across cross-origin navigation.
- Live reload with pluggable detectors: URL body hashing (`--watch-url`,
  `--watch-interval`) and local file mtimes (`--watch-file`), with state in the footer.
- `wontfit shoot` for PNG screenshots via Playwright, which stays optional.
- Unit tests (`python3 -m unittest`), GitHub Actions on 3.9 and 3.12, Makefile.

[Unreleased]: https://github.com/InfoDiveLabs/wontfit/compare/v0.2.1...HEAD
[0.2.1]: https://github.com/InfoDiveLabs/wontfit/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/InfoDiveLabs/wontfit/releases/tag/v0.2.0
