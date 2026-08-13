"""Browser rendering service — the other half of blueprint item 011.

This is a SEPARATE service on purpose. Playwright downloads a ~150MB Chromium
at image build time, and doing that inside Titan's own image breaks the free
Hugging Face Space build. Keeping it apart also means the crawler being slow
or crashing cannot take the platform down with it.

Titan talks to this through `core/render.py`. With `TITAN_RENDER_URL` unset,
Titan does not pretend: it detects that a page is client-rendered and reports
that its findings are unreliable, rather than publishing a confident score on
an empty shell.

Security, because this fetches URLs strangers typed into a signup form:

* **The same SSRF rules as the main app.** Only http/https, every resolved
  address must be public, and the check runs again on the final URL after
  redirects. A render service without this is a much better SSRF primitive
  than a plain fetcher — it executes JavaScript, so it can be made to read an
  internal endpoint and hand back the rendered result.
* **A shared token.** Set RENDER_TOKEN here and TITAN_RENDER_TOKEN in Titan.
  Without it anyone who finds the URL has a free headless browser.
* **Hard caps.** One page, one navigation, a wall-clock timeout, and a
  response size limit. Images, fonts and media are aborted — Titan reads
  markup, and blocking them cuts render time and bandwidth by most of it.

Run locally:
    pip install -r requirements.txt && playwright install --with-deps chromium
    uvicorn app:app --port 8080
"""

from __future__ import annotations

import ipaddress
import os
import socket
import time
import urllib.parse

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

RENDER_TOKEN = os.getenv("RENDER_TOKEN", "").strip()
NAV_TIMEOUT_MS = int(os.getenv("RENDER_NAV_TIMEOUT_MS", "30000"))
MAX_HTML_BYTES = int(os.getenv("RENDER_MAX_HTML_BYTES", "3000000"))
# What to wait for. "networkidle" is tempting and wrong for sites with polling
# or chat widgets — it never settles and every render hits the timeout.
WAIT_UNTIL = os.getenv("RENDER_WAIT_UNTIL", "domcontentloaded")
# A short settle after DOM ready, for frameworks that hydrate immediately
# after. Measured in ms; the default is deliberately small.
SETTLE_MS = int(os.getenv("RENDER_SETTLE_MS", "1200"))

BLOCKED_HOSTNAMES = frozenset({
    "localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback",
    "metadata", "metadata.google.internal", "instance-data",
})

BLOCKED_RESOURCES = {"image", "media", "font"}

app = FastAPI(title="Titan Renderer", version="1.0.0")


class RenderIn(BaseModel):
    url: str = Field(..., min_length=8)
    wait_ms: int = Field(default=SETTLE_MS, ge=0, le=10000)


def _is_public(addr: str) -> bool:
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False
    if not ip.is_global:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        return ip.ipv4_mapped.is_global
    return True


def check_url(url: str) -> str:
    """Same rules as the main app's safe_fetch. Raises HTTPException(400)."""
    parsed = urllib.parse.urlparse((url or "").strip())
    if parsed.scheme.lower() not in ("http", "https"):
        raise HTTPException(400, "Only http and https can be rendered.")
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host:
        raise HTTPException(400, "That address has no hostname.")
    if host in BLOCKED_HOSTNAMES:
        raise HTTPException(400, f"{host} is not a public website.")
    try:
        infos = socket.getaddrinfo(
            host, parsed.port or (443 if parsed.scheme == "https" else 80),
            proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise HTTPException(400, f"{host} does not resolve.")
    addrs = {i[4][0] for i in infos}
    bad = [a for a in addrs if not _is_public(a)]
    if bad:
        raise HTTPException(
            400, f"{host} resolves to a private or reserved address ({bad[0]}).")
    return url.strip()


def _authorise(header: str | None) -> None:
    if not RENDER_TOKEN:
        return
    expected = f"Bearer {RENDER_TOKEN}"
    # Constant-time compare: this is a bearer token on a public URL.
    import hmac
    if not header or not hmac.compare_digest(header, expected):
        raise HTTPException(401, "Unauthorized")


@app.get("/health")
def health() -> dict:
    """Reports whether a browser can ACTUALLY launch, not just that we booted.

    A container whose Chromium failed to install answers 200 on a naive health
    check and then fails every render. This launches one.
    """
    try:
        from playwright.sync_api import sync_playwright
        started = time.monotonic()
        with sync_playwright() as p:
            browser = p.chromium.launch(args=["--no-sandbox"])
            version = browser.version
            browser.close()
        return {"ok": True, "browser": version,
                "launch_ms": round((time.monotonic() - started) * 1000, 1),
                "token_required": bool(RENDER_TOKEN)}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}",
                "token_required": bool(RENDER_TOKEN)}


@app.post("/render")
def render(req: RenderIn,
           authorization: str | None = Header(default=None)) -> dict:
    """Render one page and return its HTML after JavaScript has run."""
    _authorise(authorization)
    url = check_url(req.url)

    from playwright.sync_api import sync_playwright

    started = time.monotonic()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(args=["--no-sandbox",
                                              "--disable-dev-shm-usage"])
            try:
                context = browser.new_context(
                    user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                "AppleWebKit/537.36 (KHTML, like Gecko) "
                                "Chrome/124.0 Safari/537.36"),
                    viewport={"width": 1280, "height": 900},
                    java_script_enabled=True)
                page = context.new_page()
                # Titan reads markup. Images and fonts are most of the bytes
                # and none of the value.
                page.route("**/*", lambda route: (
                    route.abort()
                    if route.request.resource_type in BLOCKED_RESOURCES
                    else route.continue_()))
                response = page.goto(url, wait_until=WAIT_UNTIL,
                                     timeout=NAV_TIMEOUT_MS)
                # The SSRF check ran on the URL we were given; a redirect can
                # land somewhere else entirely, so check where we ended up.
                final = page.url
                if final != url:
                    check_url(final)
                if req.wait_ms:
                    page.wait_for_timeout(req.wait_ms)
                html = page.content()
                status = response.status if response else None
            finally:
                browser.close()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"Render failed: {type(e).__name__}: {e}")

    if len(html.encode("utf-8", "ignore")) > MAX_HTML_BYTES:
        html = html[:MAX_HTML_BYTES]

    return {
        "ok": True,
        "url": url,
        "final_url": final,
        "status": status,
        "html": html,
        # Measured, not estimated.
        "render_ms": round((time.monotonic() - started) * 1000, 1),
    }
