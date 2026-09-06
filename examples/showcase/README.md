# Ledgerly showcase

A fake expense-tracking product site plus its app dashboard, served by a
standard-library Python server that sends `X-Frame-Options: DENY` and a CSP
with `frame-ancestors 'none'`. Try phoneframes against it without having your
own app running:

```sh
make showcase
# or by hand:
python3 examples/showcase/server.py &
phoneframes --upstream http://localhost:3939 --pages /,/pricing,/dashboard,/terms --open
```

## Planted bugs

| Where | Bug | Which diagnostic catches it |
|---|---|---|
| `/` | hero screenshot has `width: 760px; max-width: none` | overflow, culprit `img.shot` |
| `/pricing` | comparison table with `min-width: 780px` and no scroll wrapper | overflow, culprit `table.compare` |
| `/dashboard` | five 30x30 icon buttons in the toolbar | tap targets (5 small taps) |
| `/terms`, footers | legal text at 10px | text <12px |
| `/dashboard` | fixed app header grows to two rows below 480px height; body padding does not | visible in landscape mode |
| `/login` | absolute `Location` redirect to `/dashboard` plus a `Secure; Domain=localhost` cookie | proxy rewrites both; dashboard shows "signed in" |

The rest of the site is meant to be reasonable, so the diagnostics stay quiet
where nothing is wrong. Each bug is marked `BUG` in `site/style.css`.
