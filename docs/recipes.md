# Recipes: wontfit with your stack

wontfit does not care what serves your app; it proxies HTTP. Each recipe
below is the one command, the gotcha if there is one, and how cookies and auth
behave. Two facts apply to all of them:

- **HMR over WebSockets gets a 501 through the proxy.** wontfit only speaks
  HTTP/1.1. If your dev server's hot-reload client connects to
  `location.host` (the proxy), it will fail to connect and your framework will
  usually fall back to full reloads or log a warning. Where the framework lets
  you point the HMR client at the dev server's own host and port, the recipe
  says how; otherwise rely on wontfit's own live reload (URL body hash or
  `--watch-file`), which does not need WebSockets.
- **Cookies work.** The proxy forwards the browser's cookies for
  `127.0.0.1:8081` upstream and strips `Domain`/`Secure` from `Set-Cookie` on
  the way back, so a login performed inside a frame sticks. If your app also
  checks `Origin`/`Referer` for CSRF, they are rewritten to the upstream origin
  and the check passes.

Put the flags you always use in `wontfit.toml` (`wontfit init`) and the
commands below shrink to `wontfit`.

---

## Vite (React, Vue, Svelte, vanilla)

```sh
wontfit --upstream http://localhost:5173 --pages /,/about --open
```

Gotcha: Vite's HMR client connects to the page's host unless told otherwise.
Tell it to talk to Vite directly:

```js
// vite.config.js
export default defineConfig({
  server: {
    hmr: { host: "localhost", clientPort: 5173 },
  },
});
```

Vite 6+ `server.allowedHosts` is not an issue: the proxy sends
`Host: localhost:5173` by default.

## Next.js

```sh
wontfit --upstream http://localhost:3000 --pages /,/pricing --open
```

Gotcha: Next's HMR socket (`/_next/webpack-hmr`, or the Turbopack equivalent)
targets the page's host, so it gets a 501 through the proxy and Fast Refresh
stops; use wontfit's live reload instead (default: hashes the first page,
which Next re-renders on every save in dev). If you want Fast Refresh back, set
an absolute `assetPrefix` in development so assets and the socket go straight
to the dev server:

```js
// next.config.js
const dev = process.env.NODE_ENV !== "production";
module.exports = { assetPrefix: dev ? "http://localhost:3000" : undefined };
```

Auth: `next-auth`/Auth.js sessions are cookie-based and work. OAuth callbacks
redirect to `NEXTAUTH_URL`; keep it at the dev server URL and wontfit
rewrites the final redirect back to the proxy.

## Nuxt

```sh
wontfit --upstream http://localhost:3000 --open
```

Nuxt uses Vite under the hood; the same HMR setting applies:

```ts
// nuxt.config.ts
export default defineNuxtConfig({
  vite: { server: { hmr: { host: "localhost", clientPort: 3000 } } },
});
```

## SvelteKit

```sh
wontfit --upstream http://localhost:5173 --open
```

Same as Vite. Form actions post to the page path and work through the proxy;
`event.url.origin` will be the upstream origin (because of the Host header),
which is what you want for redirects.

## Django

```sh
python manage.py runserver 8000
wontfit --upstream http://localhost:8000 --pages /,/accounts/login/ --open
```

No HMR, so nothing to configure; `runserver` reloads on save and wontfit's
URL hash catches the new HTML. `ALLOWED_HOSTS` passes because the proxy sends
the upstream's own host. CSRF passes because `Origin` is rewritten to match.
Session cookies with `SESSION_COOKIE_SECURE = True` still stick, since the
proxy strips `Secure`. If you generate absolute URLs with
`request.build_absolute_uri`, add `--rewrite-host preserve` so they point at
the proxy.

## Flask / FastAPI

```sh
flask run --debug --port 5000          # or: uvicorn app:app --reload --port 8000
wontfit --upstream http://localhost:5000 --open
```

Nothing special. For template-only edits that do not change the first page's
HTML, add `--watch-file 'templates/**/*.html' --watch-file 'static/**'`.

## Rails

```sh
bin/dev                                 # or: bin/rails server
wontfit --upstream http://localhost:3000 --open
```

`config.hosts` passes (upstream Host is sent). Action Cable's WebSocket gets a
501 through the proxy; the rest of the page is unaffected. Turbo and signed
cookies work. For `jsbundling`/`cssbundling` watch builds, point live reload at
the built assets: `--watch-file 'app/assets/builds/**'`.

## Go

```sh
go run . # or air / templ generate --watch ...
wontfit --upstream http://localhost:8080 --open
```

If you use `air` or `templ`'s proxy for live reload, they inject a script that
opens a WebSocket or SSE connection to their own port; point wontfit at
that proxy's port rather than your app's so the injected script is the same
one you see in the browser normally. SSE passes through wontfit (it is
plain HTTP streaming); WebSockets do not.

## Laravel

```sh
php artisan serve                       # :8000
npm run dev                             # Vite on :5173
wontfit --upstream http://localhost:8000 --open
```

Laravel's Vite plugin prints asset URLs from the Vite server, so the HMR
client already talks to `localhost:5173` directly; add the Vite `server.hmr`
setting above if it does not. `APP_URL` is used for absolute URLs: either keep
it at `http://localhost:8000` (wontfit rewrites redirects) or run with
`--rewrite-host preserve`. Sanctum's SPA auth is cookie-based and works;
add the proxy origin to `SANCTUM_STATEFUL_DOMAINS` (`127.0.0.1:8081`) only if
you run with `--rewrite-host preserve`.

## Plain static site

```sh
python3 -m http.server 8000             # or any static server
wontfit --upstream http://localhost:8000 --pages /,/about.html --watch-file '**/*.html' --watch-file '**/*.css'
```

Static servers do not set framing headers, so the proxy has nothing to strip
here; you use wontfit for the side-by-side layout, the diagnostics and the
file watcher.

## Storybook

```sh
npm run storybook                       # :6006
wontfit --upstream http://localhost:6006 --widths se,pixel8,ipad \
  --pages '/iframe.html?id=components-button--primary&viewMode=story,/iframe.html?id=components-card--default&viewMode=story'
```

Preview the story iframe URLs directly rather than the manager UI; you get one
column per story per width, which is the point. Storybook's HMR is a
WebSocket and will 501; wontfit's URL hash reload is enough for stories.

## Docker Compose

```sh
docker compose up                       # app publishes 3000:3000
wontfit --upstream http://localhost:3000 --open
```

Run wontfit on the host against the published port. Do not run it inside
a container: it binds to loopback on purpose, and publishing that port would
expose a proxy that strips security headers. If the app in the container
rejects the `Host` header, pass the name it expects:
`--rewrite-host app.docker.internal:3000`.

## HTTPS dev servers (mkcert, Caddy, `--https` flags)

```sh
wontfit --upstream https://localhost:5173 --insecure --open
```

`--insecure` accepts a self-signed certificate; certificates from mkcert are
trusted by the system store and do not need it. The proxy itself is plain
HTTP on loopback, which browsers treat as a secure context, so `Secure`
cookies (rewritten) and most "secure context" APIs behave.
