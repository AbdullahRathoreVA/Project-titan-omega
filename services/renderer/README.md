# Titan renderer

The browser half of blueprint item 011. Titan's crawler is a single HTTP GET,
so on a client-rendered site it audits an empty shell. This service fetches a
page through real Chromium so the audit sees what a visitor sees.

**Titan works without it.** With `TITAN_RENDER_URL` unset, Titan detects that a
page is client-rendered and reports that its findings are unreliable for that
page, rather than publishing a confident score on a `<div id="root">`. This
service upgrades detection into rendering.

## Why it is not inside the main image

Playwright downloads ~150MB of Chromium at image build time. Doing that inside
Titan's Hugging Face Space image breaks the free-tier build. Keeping it
separate also means a slow or crashing crawler cannot take the platform down.

## Deploy

It is a plain Dockerfile, so anything that runs a container works. What it
needs: **~1GB RAM** (Chromium will OOM below that) and the ability to run a
container, not just a Python buildpack.

```bash
docker build -t titan-renderer .
docker run -p 8080:8080 -e RENDER_TOKEN=$(openssl rand -hex 24) titan-renderer
```

Then set both sides:

| Where | Variable | Value |
|---|---|---|
| The renderer | `RENDER_TOKEN` | a long random string |
| Titan | `TITAN_RENDER_URL` | `https://your-renderer-host` |
| Titan | `TITAN_RENDER_TOKEN` | the same random string |

**Set the token.** Without it, anyone who finds the URL has a free headless
browser pointed at any address they like.

## Verify it actually works

`/health` launches a real browser rather than just returning 200 — a container
whose Chromium failed to install passes a naive health check and then fails
every render.

```bash
curl -s https://your-renderer-host/health
```

Expect `{"ok": true, "browser": "Chromium/…", "launch_ms": …}`. Then, from
Titan's side, audit a client-rendered page and confirm the result carries
`rendering.rendered_with == "browser"`.

## Configuration

| Variable | Default | Notes |
|---|---|---|
| `RENDER_TOKEN` | *(none)* | Shared bearer token. Set it. |
| `RENDER_NAV_TIMEOUT_MS` | `30000` | Per-navigation cap. |
| `RENDER_WAIT_UNTIL` | `domcontentloaded` | **Not** `networkidle` — sites with polling or a chat widget never settle and every render hits the timeout. |
| `RENDER_SETTLE_MS` | `1200` | Pause after DOM ready, for frameworks that hydrate straight after. |
| `RENDER_MAX_HTML_BYTES` | `3000000` | Response cap. |

Images, fonts and media are aborted at the network layer: Titan reads markup,
and blocking them removes most of the bytes and most of the time.

## Security

Same SSRF rules as the main app — http/https only, every resolved address must
be public, and the check runs **again** on the final URL after redirects. That
last one matters more here than in a plain fetcher: this executes JavaScript,
so without it the service is an unusually capable way to read someone's
internal network and hand back the rendered result.
