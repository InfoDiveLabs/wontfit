# phoneframes

Preview any locally running web app at phone and tablet sizes, side by side, in
your normal desktop browser. Works even when the app sends `X-Frame-Options` or
a CSP `frame-ancestors` directive, and even when your browser window is
fullscreen.

Zero dependencies. Python 3.9+ standard library only. Binds to loopback.

## Quick start (10 seconds)

```sh
pipx install phoneframes            # or: pip install phoneframes
phoneframes --upstream http://localhost:3000 --open
```

That opens `http://127.0.0.1:8081/__phoneframes` with your app's `/` rendered
at 375, 393 and 430 CSS px. Type more pages and widths in the bar, or deep-link:

```
/__phoneframes?p=/,/pricing&w=375,se,ipad&h=900
/__phoneframes?p=/dashboard&w=393&o=l          # landscape
```

No install needed either: `git clone` and `python3 -m phoneframes ...`.

## What it looks like

<!-- screenshot placeholder: docs/phoneframes.png (harness with three frames, one flagged red for overflow) -->
> Screenshot/GIF coming. Run `python3 tests/demo_upstream.py` then
> `phoneframes --upstream http://localhost:3999 --pages /,/wide --open` to see it live.

## Why not DevTools device mode?

Device mode is great for one page at one size. It is poor at the thing you do
while iterating on a responsive layout: watching `/`, `/pricing` and `/checkout`
at three phone widths *at the same time*, after every save, without clicking
through a dropdown per tab. phoneframes puts them all on one screen, keeps the
layout in a URL you can send to a teammate, reloads every frame when the app
changes, and tells you which frame overflows and which element did it. And it
does not care that your app forbids framing: the proxy removes exactly the two
headers that say so, leaves the rest of the security policy in place, and only
ever listens on `127.0.0.1`.

## Features

- **Proxy** - forwards every method and body, streams responses, strips
  `X-Frame-Options` and only the `frame-ancestors` part of the CSP, rewrites
  absolute `Location` headers back to the proxy, forwards cookies both ways,
  passes gzip/br/zstd through untouched, HTTPS upstreams with `--insecure` for
  self-signed certs, and `--rewrite-host` for apps that check `Host`.
- **Harness** - pages list, typed widths or device presets (iPhone SE 375,
  iPhone 15 393, iPhone 15 Plus 430, Pixel 8 412, Galaxy Fold 344, iPad Mini
  744, iPad 820, laptop 1280), height, landscape toggle, one column per page x
  width, state in the URL, Reload frames (`r`).
- **Diagnostics per frame** (best-effort, same-origin only)
  - horizontal overflow: flagged red, with the offending elements by
    tag/class and their left..right bounds
  - tap targets smaller than 44x44 CSS px: warning count, plus an outline
    overlay inside the frame (`t`)
  - text under 12px: count
  - inspect (`i`): hover an element in one frame and it is highlighted, with its
    size, in every frame
- **Live reload** - polls a URL and hashes the body (default: your first page,
  every 2s), or watches local files by mtime with `--watch-file`, or both. The
  footer shows what is watched, the current fingerprint and the last change.
- **Screenshots** - `phoneframes shoot` writes PNGs with Playwright, if you have
  it installed. The core never imports it.

## Flags

`phoneframes [options]` starts the proxy and harness.

| Flag | Default | What it does |
|---|---|---|
| `--upstream URL` | `http://localhost:3000` | The app to preview. Scheme optional. |
| `--port N` | `8081` | Port to listen on (always `127.0.0.1`). |
| `--open` | off | Open the harness in your default browser. |
| `--pages /a,/b` | `/` | Pages to show, comma-separated. |
| `--widths 375,se,ipad` | `375,393,430` | CSS widths, numbers or preset keys: `se iphone15 iphone15plus pixel8 fold ipadmini ipad laptop`. |
| `--height N` | `800` | Frame height in CSS px. |
| `--cookie name=value` | | Sent with every upstream request. Repeatable. |
| `--header 'Name: value'` | | Sent with every upstream request. Repeatable. |
| `--insecure` | off | Accept self-signed certificates on an HTTPS upstream. |
| `--rewrite-host HOST` | upstream's host | `Host` header sent upstream. `preserve` forwards the browser's (`127.0.0.1:8081`); any other value is sent literally. |
| `--watch-url URL` | first page | Poll this URL through the upstream and reload frames when its body changes. |
| `--watch-file GLOB` | | Watch local files by mtime and size instead of, or as well as, a URL. Repeatable, `**` allowed. |
| `--watch-interval S` | `2` | Seconds between checks. |
| `--no-watch` | off | Disable live reload. |
| `-v`, `--verbose` | off | Log each proxied request with status and timing. |
| `--version` | | Print the version. |

`phoneframes shoot [options]` takes the shared flags above (`--upstream`,
`--pages`, `--widths`, `--height`, `--cookie`, `--header`, `--insecure`) plus:

| Flag | Default | What it does |
|---|---|---|
| `--out DIR` | `shots` | Where to write `<page>-<w>x<h>.png`. |
| `--full-page` | off | Capture the whole scrollable page instead of the viewport. |
| `--landscape` | off | Swap width and height. |

Install the optional dependency with `pip install 'phoneframes[shoot]'` then
`playwright install chromium`. Without it the command prints how to get it and
exits 2.

## Harness keyboard shortcuts

Shortcuts apply when the harness itself has focus (click the dark background
first if you were typing inside a frame).

| Key | Action |
|---|---|
| `r` | Reload every frame |
| `t` | Toggle the tap-target overlay |
| `i` | Toggle inspect |
| `Esc` | Leave a text field |

## URL state

Everything in the bar lives in the query string, so a layout is a link:
`p` pages, `w` widths (numbers or preset keys), `h` height, `o=l` landscape,
`live=0` live reload off. Missing or invalid values fall back to what the CLI
was started with.

## FAQ

**The app sets a CSP. Does phoneframes weaken it?**
Only `frame-ancestors` is removed. `script-src`, `connect-src`, nonces and the
rest are forwarded exactly as sent. `Content-Security-Policy-Report-Only` gets
the same treatment. `X-Frame-Options` is dropped entirely because it has no
other purpose.

**Do cookies work? I need to be logged in.**
Yes. The browser's cookies for `127.0.0.1:8081` are forwarded to the upstream,
and upstream `Set-Cookie` headers come back with `Domain` and `Secure` removed
so they stick to the proxy's plain-HTTP loopback origin (`SameSite=None`
becomes `Lax`). Log in once inside any frame, or pass a session cookie on the
command line: `--cookie session=abc123`. Bearer tokens go in
`--header 'Authorization: Bearer ...'`.

**HTTPS upstream?**
`--upstream https://localhost:5173`. Certificates are verified by default;
`--insecure` accepts self-signed ones. The proxy itself always speaks plain
HTTP, which browsers treat as a secure context on loopback.

**The app redirects me to `http://localhost:3000/...` and I lose the proxy.**
Absolute `Location` headers that point at the upstream origin are rewritten
to the proxy. Redirects the app constructs client-side from a hard-coded host
cannot be caught; use `--rewrite-host preserve` so the app builds URLs from the
proxy's `Host` header instead.

**The app rejects requests because of the `Host` header (Django
`ALLOWED_HOSTS`, Rails `hosts`, Vite `server.allowedHosts`).**
By default phoneframes sends the upstream's own host, so those checks pass.
`Origin` and `Referer` are rewritten to match, which keeps CSRF origin checks
happy. If you want the app to see the proxy's host instead, pass
`--rewrite-host preserve`.

**A frame says "cross-origin".**
The page inside navigated to another origin (an OAuth provider, a CDN error
page). The frame still shows it, but diagnostics need same-origin access and
are switched off for that frame until it comes back.

**Why is my link flagged as a small tap target?**
Anything interactive under 44x44 CSS px is counted, matching WCAG 2.5.5 and
Apple's HIG. Inline text links usually trip it; that is a judgement call, which
is why it is a warning count and not a red flag.

**Live reload does not fire.**
The default detector hashes the body of your first page; a CSS-only change
that leaves the HTML byte-identical will not trigger it. Use
`--watch-file 'src/**/*'` for file-based detection, or `--watch-url` for a
URL that changes on every build (a manifest, a hashed asset URL).

**Can I bind to 0.0.0.0 to test from a real phone?**
No, on purpose. See below.

## What it deliberately does not do

- **WebSockets.** `Upgrade: websocket` requests get a 501. Frameworks whose HMR
  client connects to a hard-coded port will still work if that port is the
  upstream's; ones that connect to `location.host` will fail to connect and
  fall back to polling or nothing. phoneframes' own live reload does not need
  it.
- **HTTP/2 or server push.** The proxy is HTTP/1.1 on both sides.
- **Connection pooling.** One fresh upstream connection per request.
- **Rewriting bodies.** HTML, JS and JSON are passed through byte-for-byte; no
  URL rewriting happens inside content.
- **Trailers**, and request bodies without `Content-Length` or chunked framing.

## Security note

phoneframes binds to `127.0.0.1` only and has no authentication, because it is
a development tool that removes framing protection from whatever you point it
at. Never expose the port on a network interface, through a tunnel, or from a
container port mapping. If you need to preview on a real device, use the app's
own dev server on your LAN, not this proxy.

## Development

```sh
python3 -m unittest        # tests, stdlib only
make lint                  # ruff, if installed
python3 tests/demo_upstream.py            # throwaway app that blocks framing
python3 -m phoneframes --upstream http://localhost:3999 --pages /,/wide --open
```

See [CONTRIBUTING.md](CONTRIBUTING.md). Licensed under [MIT](LICENSE).
