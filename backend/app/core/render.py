"""Is this page the real page, or an empty shell a browser fills in later?

Titan's crawler is a single HTTP GET, so for a client-rendered site (React,
Vue, Angular, Next in SPA mode, many Wix and Squarespace templates) it only
sees the shell: a `<div id="root">` and a script tag. Auditing that would
report "no H1", "no schema", "thin content" about the shell, not the site -
worse than no audit, because a confident wrong finding looks like a right one.

Two parts:

1. Detect the shell and say so. Free, no dependency. A page that's mostly
   script tags with almost no visible text and an empty root container can't
   be audited over HTTP, so the audit is marked unreliable with the reason
   instead of getting a confident F.
2. Render it. Needs Chromium, which can't go in the Space image (downloading
   the browser at build time breaks the free build), so it runs as a separate
   service (`services/renderer/`) and this is the client. With
   `TITAN_RENDER_URL` unset there's no renderer, and this says so.

`rendered_with` is always reported ("http" or "browser"), so a caller always
knows whether JavaScript ran.
"""

from __future__ import annotations

import os
import re
from typing import Optional

# The separate Playwright service. Unset on the free tier, in which case
# everything below falls back to detection only.
RENDER_URL = os.getenv("TITAN_RENDER_URL", "").strip().rstrip("/")
RENDER_TOKEN = os.getenv("TITAN_RENDER_TOKEN", "").strip()
RENDER_TIMEOUT = float(os.getenv("TITAN_RENDER_TIMEOUT", "45"))

# Below this much visible text, a page carries no usable content. A Next.js
# SPA shell is around 0-80 characters; a thin but real brochure page 400+.
SHELL_TEXT_CHARS = 250

# Containers a framework mounts into. An empty one is the strongest single
# signal - the markup literally says "content goes here later".
_EMPTY_MOUNT = re.compile(
    r'<div[^>]+id=["\'](?:root|app|__next|__nuxt|main-app)["\'][^>]*>\s*</div>',
    re.I)

_FRAMEWORK_MARKERS = (
    ("__NEXT_DATA__", "Next.js"),
    # The App Router doesn't emit __NEXT_DATA__; it streams into self.__next_f,
    # so Next 13+ sites need this marker too.
    ("__next_f", "Next.js"),
    ("data-reactroot", "React"),
    ("__NUXT__", "Nuxt"),
    ("ng-version", "Angular"),
    ("ng-app", "AngularJS"),
    ("data-v-app", "Vue"),
    ("__remixContext", "Remix"),
    ("__sveltekit", "SvelteKit"),
)


def _visible_text(html: str) -> str:
    out = re.sub(r"<(script|style|template|noscript)\b.*?</\1>", " ", html,
                 flags=re.I | re.S)
    out = re.sub(r"<!--.*?-->", " ", out, flags=re.S)
    out = re.sub(r"<[^>]+>", " ", out)
    return re.sub(r"\s+", " ", out).strip()


def inspect(html: str) -> dict:
    """Evidence about whether this HTML is a shell, not a bare boolean.

    Every field is counted from the document, so a reader can check the
    verdict.
    """
    html = html or ""
    text = _visible_text(html)
    scripts = len(re.findall(r"<script\b", html, re.I))
    empty_mount = bool(_EMPTY_MOUNT.search(html))
    frameworks = sorted({name for marker, name in _FRAMEWORK_MARKERS
                         if marker in html})
    noscript = bool(re.search(
        r"<noscript[^>]*>.*?(enable|turn on|requires)\s+javascript",
        html, re.I | re.S))

    # An empty mount point or a noscript warning is close to proof on its own.
    # Otherwise it takes both little text and a framework doing the rendering: a
    # short page with no JavaScript is thin content, a different finding with a
    # different fix.
    thin = len(text) < SHELL_TEXT_CHARS
    client_rendered = bool(
        empty_mount or noscript or (thin and (frameworks or scripts >= 3)))

    # Reasons must support the verdict, not just list signals - "15 script tags
    # with almost no text" next to a page with 312 characters contradicts itself.
    reasons = []
    if client_rendered:
        if empty_mount:
            reasons.append("the framework's mount element is empty in the HTML")
        if noscript:
            reasons.append("the page carries a <noscript> notice telling "
                           "visitors to enable JavaScript")
        if thin:
            reasons.append(f"only {len(text)} characters of visible text "
                           f"were served")
            if frameworks:
                reasons.append(f"framework markers present: "
                               f"{', '.join(frameworks)}")
            elif scripts >= 3:
                reasons.append(f"{scripts} script tags and almost no text")

    return {
        "client_rendered": client_rendered,
        "visible_text_chars": len(text),
        "script_tags": scripts,
        "empty_mount_element": empty_mount,
        "noscript_warning": noscript,
        "frameworks": frameworks,
        "reasons": reasons,
    }


def available() -> bool:
    """Whether a browser renderer is configured."""
    return bool(RENDER_URL)


def status() -> dict:
    """What Titan can and can't do about JavaScript on this deployment."""
    if available():
        return {
            "available": True, "url": RENDER_URL,
            "note": ("A separate browser service is configured. Pages that "
                     "look client-rendered are fetched through it and the "
                     "audit reports rendered_with='browser'."),
        }
    return {
        "available": False, "url": None,
        "note": ("No browser renderer is configured, so Titan audits the HTML "
                 "the server sends. Pages that render in the browser are "
                 "DETECTED and the audit says its findings are unreliable for "
                 "them — it does not publish a confident score on a shell. Set "
                 "TITAN_RENDER_URL to a deployed services/renderer to close "
                 "this gap. Chromium cannot ship inside this container: the "
                 "browser download at image build time breaks the free-tier "
                 "build."),
    }


def render(url: str, *, timeout: Optional[float] = None) -> tuple[Optional[str], str]:
    """Fetch `url` through the browser service. Returns (html, error).

    Returns (None, reason) when no renderer is configured, never a silent
    fallback that leaves the caller thinking JavaScript ran.
    """
    if not RENDER_URL:
        return None, "No browser renderer is configured (TITAN_RENDER_URL)."
    try:
        import httpx
        from . import safe_fetch

        safe_fetch.check(url)
        headers = {"Content-Type": "application/json"}
        if RENDER_TOKEN:
            headers["Authorization"] = f"Bearer {RENDER_TOKEN}"
        with httpx.Client(timeout=timeout or RENDER_TIMEOUT) as c:
            r = c.post(f"{RENDER_URL}/render", json={"url": url},
                       headers=headers)
        if r.status_code >= 400:
            return None, f"The render service replied {r.status_code}."
        data = r.json()
        html = data.get("html")
        if not html:
            return None, (data.get("error")
                          or "The render service returned no HTML.")
        return html, ""
    except Exception as e:
        return None, f"The render service could not be reached ({type(e).__name__})."


def fetch_best(url: str, *, user_agent: str, timeout: float,
               fetcher=None) -> tuple[Optional[str], Optional[str], int, dict]:
    """Fetch a page, using the browser only when the plain GET looks like a shell.

    Returns (html, error, status, rendering); `rendering` records which path
    produced the HTML and the evidence. The browser isn't used for every page:
    it's slower, costs a request to someone else's server, and most sites
    don't need it.

    `fetcher` lets the caller supply its own plain-HTTP step. `client_seo`
    passes its `_fetch`, which its tests substitute; calling safe_fetch
    directly here would bypass that and send those tests to the real network.
    """
    if fetcher is not None:
        html, err, status_code = fetcher(url)
    else:
        from . import safe_fetch
        html, err, status_code = safe_fetch.fetch(url, user_agent=user_agent,
                                                  timeout=timeout)
    if html is None:
        return None, err, status_code, {
            "rendered_with": None, "client_rendered": None,
            "renderer_available": available(),
            "note": "The page could not be fetched at all.",
        }

    evidence = inspect(html)
    rendering = {**evidence, "rendered_with": "http",
                 "renderer_available": available()}

    if not evidence["client_rendered"]:
        rendering["note"] = ("The server sent the full page, so an HTTP fetch "
                             "is the whole story here.")
        return html, None, status_code, rendering

    rendered, render_err = render(url)
    if rendered:
        after = inspect(rendered)
        rendering.update({
            "rendered_with": "browser",
            "visible_text_chars_after_render": after["visible_text_chars"],
            "note": ("This page renders in the browser, so it was fetched "
                     "again through a real browser. The findings below are "
                     "about the rendered page."),
        })
        return rendered, None, status_code, rendering

    # The key branch: Titan can't see this page properly, and says so.
    rendering.update({
        "rendered_with": "http",
        "reliable": False,
        "render_error": render_err,
        "note": ("This page builds itself in the browser and Titan fetched "
                 "only what the server sent, so the findings below describe an "
                 "empty shell rather than the site a visitor sees. They are "
                 "NOT reliable for this page."),
    })
    return html, None, status_code, rendering
