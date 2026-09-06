# Changelog

All notable changes to phoneframes are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.0] - 2026-09-06

### Added
- Reverse proxy on `127.0.0.1` that strips `X-Frame-Options` and the
  `frame-ancestors` directive from `Content-Security-Policy` (keeping the rest),
  rewrites absolute `Location` headers back to the proxy, forwards cookies both
  ways (dropping `Domain`/`Secure` so they stick on the loopback origin), streams
  bodies, passes `Content-Encoding` through untouched, and supports HTTPS
  upstreams with `--insecure` for self-signed certificates.
- `--rewrite-host` to control the upstream `Host` header (`preserve` or a literal).
- Harness at `/__phoneframes`: pages, typed widths or device presets (iPhone SE,
  iPhone 15, iPhone 15 Plus, Pixel 8, Galaxy Fold, iPad Mini, iPad, laptop),
  height, orientation toggle, one column per page x width, state in the URL,
  "Reload frames" with the `r` shortcut.
- Per-frame diagnostics: horizontal overflow with culprit elements, tap targets
  under 44x44 CSS px with a toggleable overlay, text under 12px, and cross-frame
  inspect highlighting. All best-effort and safe across cross-origin navigation.
- Live reload with pluggable detectors: URL body hashing (`--watch-url`,
  `--watch-interval`) and local file mtimes (`--watch-file`), with state in the footer.
- `phoneframes shoot` for PNG screenshots via Playwright, which stays optional.
- Unit tests (`python3 -m unittest`), GitHub Actions on 3.9 and 3.12, Makefile.
