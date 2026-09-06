# Contributing

Thanks for looking. phoneframes is deliberately small; the best contributions
keep it that way.

## Ground rules

- **Zero runtime dependencies for the core.** Anything that needs a third-party
  package goes behind a guarded import in an optional subcommand (see
  `phoneframes/shoot.py`) or does not go in.
- **Python 3.9+.** CI runs 3.9 and 3.12; do not use syntax or stdlib features
  newer than 3.9 (no `match`, no `X | Y` unions at runtime).
- **Loopback only.** The proxy binds to `127.0.0.1` and has no auth. Do not add
  a flag to bind elsewhere.
- **Honest diagnostics.** The in-frame checks are heuristics. Prefer fewer,
  explainable signals over clever ones that are sometimes wrong.

## Setup

```sh
git clone https://github.com/infodive/phoneframes
cd phoneframes
python3 -m unittest            # or: make test
make lint                      # ruff, if installed (pip install ruff)
python3 tests/demo_upstream.py # a throwaway app that blocks framing, on :3999
python3 -m phoneframes --upstream http://localhost:3999 --pages /,/wide --open
```

## Layout

| File | What lives there |
|---|---|
| `phoneframes/proxy.py` | Header rewriting (pure functions) and the streaming handler |
| `phoneframes/harness.py` | `HarnessState` (URL serialisation) and the harness routes |
| `phoneframes/assets/harness.html` | The page: controls, frames, live reload polling |
| `phoneframes/assets/diagnostics.js` | Overflow / tap target / small text / inspect, run against same-origin frames |
| `phoneframes/watch.py` | Change detectors and the rate-limited `Watcher` |
| `phoneframes/config.py` | `phoneframes.toml` / `[tool.phoneframes]` discovery, the TOML-subset parser, CLI-default merging |
| `phoneframes/check.py` | `check`: report shaping, exit codes, table (pure) and the Playwright runner |
| `phoneframes/shoot.py` | `shoot`: per-frame PNGs and the contact sheet |
| `phoneframes/_browser.py` | Shared guarded Playwright import and context setup |
| `phoneframes/cli.py` | Argument parsing, config merging, and the `serve` / `shoot` / `check` / `init` commands |
| `examples/showcase/` | The Ledgerly demo site with planted bugs (`make showcase`) |
| `docs/screenshots.py` | Regenerates `docs/images` (maintainers; needs Playwright and Pillow) |

## Pull requests

1. Add or update a unit test in `tests/`. Header rewriting and state
   serialisation are pure functions; test them without sockets.
2. Run `python3 -m unittest` on the oldest Python you have.
3. Add a line under "Unreleased" in `CHANGELOG.md`.
4. Keep the README flag table in sync with `cli.py`.

## Writing a change detector

Subclass `phoneframes.watch.ChangeDetector`, implement `probe()` to return a
short fingerprint string (or `None` when the target is unreachable), and
`describe()` for the footer. Wire it up in `build_detector`.
