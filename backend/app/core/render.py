"""Is this page actually the page, or an empty shell a browser fills in later?

Blueprint item 011. Titan's crawler is a single HTTP GET, so for any
client-rendered site — React, Vue, Angular, Next in SPA mode, most Wix and
Squarespace templates — what it audits is the shell: a `<div id="root">` and a
script tag. It then reports "no H1", "no schema", "thin content" with total
confidence, and every one of those findings is about the shell rather than
about the site.

That is worse than having no crawler for those sites, because a wrong finding
delivered confidently is indistinguishable from a right one. It is the single
largest correctness gap in the product and it affects a large share of the
small-business market.

There are two halves to fixing it, and **only one of them needs a server**:

1. **Detect the shell and say so.** Free, no dependency, works today. A page
   that is mostly script tags with almost no visible text and an empty root
   container is not a page Titan can audit over HTTP, and the honest response
   is to mark the audit unreliable and name the reason — not to publish a
   confident F.
2. **Render it.** Needs Chromium, which cannot go in the Space image: the
   browser download at Docker build time breaks the free build. So it lives in
   a separate service (`services/renderer/`) and this module is the client for
   it. With `TITAN_RENDER_URL` unset there is no renderer, and this module says
   so plainly rather than pretending.

`rendered_with` is always reported: `"http"` or `"browser"`. A caller can
never be left guessing whether JavaScript ran, and Titan never claims a
rendered audit it did not perform.
"""

from __future__ import annotations

import os
import re
from typing import Optional

# The separate Playwright service. Unset on the free tier, and everything
# below degrades to detection-only when it is.
RENDER_URL = os.getenv("TITAN_RENDER_URL", "").strip().rstrip("/")
RENDER_TOKEN = os.getenv("TITAN_RENDER_TOKEN", "").strip()
RENDER_TIMEOUT = float(os.getenv("TITAN_RENDER_TIMEOUT", "45"))

# Below this much visible text, a page is not carrying content a reader or a
# crawler could use. Chosen against real shells: a Next.js SPA shell lands
# around 0-80 characters, a thin but genuine brochure page around 400+.
SHELL_TEXT_CHARS = 250

# Containers a framework mounts into. An EMPTY one is the strongest single
# signal — the markup literally says "content goes here later".
_EMPTY_MOUNT = re.compile(
    r'<div[^>]+id=["\'](?:root|app|__next|__nuxt|main-app)["\'][^>]*>\s*</div>',
    re.I)

_FRAMEWORK_MARKERS = (
    ("__NEXT_DATA__", "Next.js"),
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
    """Evidence about whether this HTML is a shell. Never a bare boolean.

    Every field is something counted in the document, so a reader can check
    the verdict rather than trust it.
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
    # Otherwise it takes both a lack of text AND a framework doing the
    # rendering — a genuinely short page that ships no JavaScript is thin
    # content, which is a different finding with a different fix.
    thin = len(text) < SHELL_TEXT_CHARS
    client_rendered = bool(
        empty_mount or noscript or (thin and (frameworks or scripts >= 3)))

    reasons = []
    if empty_mount:
        reasons.append("the framework's mount element is empty in the HTML")
    if noscript:
        reasons.append("the page carries a <noscript> notice telling visitors "
                       "to enable JavaScript")
    if thin:
        reasons.append(f"only {len(text)} characters of visible text were served")
    if frameworks:
        reasons.append(f"framework markers present: {', '.join(frameworks)}")
    if scripts >= 3 and not frameworks:
        reasons.append(f"{scripts} script tags with almost no text")

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
    """Whether a browser renderer is actually configured. No guessing."""
    return bool(RENDER_URL)


def status() -> dict:
    """What Titan can and cannot do about JavaScript, stated plainly."""
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

    Returns (None, reason) when no renderer is configured — never a silent
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

    Returns (html, error, status, rendering) where `rendering` always records
    which path produced the HTML and what the evidence was. The browser is not
    used for every page on purpose — it is slower and costs a request against
    someone else's server, and most sites do not need it.

    `fetcher` lets the caller supply its own plain-HTTP step. `client_seo`
    passes its `_fetch`, which is the seam its tests already substitute; going
    straight to safe_fetch here would have silently bypassed that and left
    eight tests hitting the real network.
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

    # The important branch. Titan cannot see this page properly and says so.
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
