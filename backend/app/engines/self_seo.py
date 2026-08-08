"""Titan audits its own website, continuously, with the engine it sells.

Two reasons this exists, and the second is the important one.

1. Titan was failing its own audit. Measured on the live site before this
   module: no sitemap.xml (404) and zero JSON-LD blocks — the exact two
   findings its own engine reports as *critical* to paying clients. A product
   that sells SEO while scoring badly on its own SEO is the easiest objection
   in the world to raise, and the hardest to answer.

2. It is the strongest trust signal available and it costs nothing. Anyone can
   claim their tool is good. "Titan scores 94/100 on its own audit, re-checked
   every 6 hours, and here are the findings it still has open" is a claim that
   can be verified by the reader in about ten seconds — and it is verifiable
   precisely because the same code produced it.

The score is published truthfully or not at all. If Titan's own site regresses,
the number goes down in public. Publishing a hardcoded 100 would be exactly the
fabrication the rest of this codebase refuses to do, and would be found out by
the first prospect who ran a competing audit.

Runs on the existing heartbeat — no new process, no new cost.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Optional

from ..core import events
from . import client_seo

# The public origin. Overridable so a fork does not audit Abdullah's domain.
SITE = os.getenv("TITAN_PUBLIC_URL", "https://titanomega-ai.com").rstrip("/")

# Six hours. Frequent enough to catch a regression the day it ships, rare
# enough that Titan is not a meaningful share of its own traffic.
INTERVAL = float(os.getenv("TITAN_SELF_SEO_INTERVAL", str(6 * 3600)))

# Pages worth advertising and worth auditing. Everything else on the site is
# behind a login and has no business in a sitemap.
PUBLIC_PATHS = (
    ("/", 1.0, "daily"),
    ("/pricing", 0.9, "weekly"),
    # The conversion page. It is the second most valuable URL on the site
    # after the homepage — leaving it out of the sitemap while auditing
    # clients for missing pages would be the same mistake twice.
    ("/join", 0.9, "weekly"),
    ("/privacy", 0.3, "yearly"),
    ("/portal", 0.4, "monthly"),
)

_lock = threading.RLock()
_last: dict = {}
_last_run = 0.0


def sitemap_xml() -> str:
    """A real sitemap. Titan's audit reports a missing one as a medium finding
    on client sites; shipping without one was indefensible."""
    today = time.strftime("%Y-%m-%d", time.gmtime())
    # The landing pages are the only content Titan has that a search engine
    # can match a real query against. Leaving them out of its own sitemap
    # while auditing clients for exactly that would be the same mistake twice.
    try:
        from . import landing
        paths = list(PUBLIC_PATHS) + landing.all_paths()
    except Exception:
        paths = list(PUBLIC_PATHS)
    urls = "\n".join(
        f"  <url>\n"
        f"    <loc>{SITE}{path}</loc>\n"
        f"    <lastmod>{today}</lastmod>\n"
        f"    <changefreq>{freq}</changefreq>\n"
        f"    <priority>{prio}</priority>\n"
        f"  </url>"
        for path, prio, freq in paths
    )
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            f"{urls}\n</urlset>\n")


def robots_txt() -> str:
    """Allow crawling, point at the sitemap, keep private surfaces out.

    Disallowing /api matters: an indexed JSON endpoint is a support ticket
    waiting to happen, and the client portal must never appear in results.
    """
    return (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /api/\n"
        "Disallow: /portal\n"
        "Disallow: /clients\n"
        "Disallow: /docs\n"
        "\n"
        "# AI answer engines are welcome — being quotable is the point.\n"
        "User-agent: GPTBot\nAllow: /\n"
        "User-agent: PerplexityBot\nAllow: /\n"
        "User-agent: ClaudeBot\nAllow: /\n"
        "\n"
        f"Sitemap: {SITE}/sitemap.xml\n"
    )


def structured_data() -> dict:
    """JSON-LD for the product itself.

    Titan's audit tells clients that only ~17% of sites publish schema and that
    it is how AI Overviews and ChatGPT Search decide what to quote. Titan
    published none. Offers are generated from the real plan table so the
    marked-up price can never drift from the price actually charged.
    """
    from ..core import billing

    offers = [
        {
            "@type": "Offer",
            "name": p.name,
            "price": f"{p.price_usd:.2f}",
            "priceCurrency": "USD",
            "url": f"{SITE}/pricing",
            "availability": "https://schema.org/InStock",
        }
        for p in (billing.PLANS[k] for k in billing.ORDER)
    ]
    return {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "SoftwareApplication",
                "name": "Titan Omega",
                "applicationCategory": "BusinessApplication",
                "operatingSystem": "Web",
                "url": SITE,
                "description": (
                    "SEO, local ranking and legal compliance audits for any "
                    "business in any jurisdiction. Technical, local and legal "
                    "findings are scored separately, never averaged."),
                "featureList": [
                    "Technical SEO audit",
                    "Local ranking factor scoring on published 2026 weights",
                    "Legal compliance across 9 jurisdictions "
                    "(Impressum / §5 DDG, GDPR consent)",
                    "24/7 monitoring with regression alerts",
                    "Client-ready PDF reports",
                ],
                "offers": offers,
            },
            {
                "@type": "Organization",
                "name": "Titan Omega",
                "url": SITE,
                "logo": f"{SITE}/icons/icon-512.png",
            },
            {
                "@type": "WebSite",
                "name": "Titan Omega",
                "url": SITE,
            },
        ],
    }


def audit_self(force: bool = False) -> dict:
    """Run Titan's own audit against Titan's own site."""
    global _last_run
    if not force and time.monotonic() - _last_run < INTERVAL:
        with _lock:
            return dict(_last)
    _last_run = time.monotonic()

    result = client_seo.audit(
        SITE, business_name="Titan Omega", city="", country="",
        industry="software")

    snapshot = {
        "url": SITE,
        "checked_at": time.time(),
        "ok": result.get("ok", False),
        "score": result.get("score"),
        "grade": result.get("grade"),
        "passed": result.get("passed", []),
        "failed": result.get("failed", []),
        "open_findings": [
            {"id": f["id"], "severity": f["severity"], "title": f["title"]}
            for f in result.get("findings", [])
        ][:12],
        "counts": result.get("counts", {}),
        "error": result.get("error"),
    }
    with _lock:
        _last.clear()
        _last.update(snapshot)

    events.emit(events.AUDIT_FINISHED, {
        "target": "self", "score": snapshot.get("score"),
        "grade": snapshot.get("grade"),
        "findings": len(snapshot["open_findings"]),
    }, actor="self-seo",
        severity="info" if (snapshot.get("score") or 0) >= 80 else "warn")
    return snapshot


def report() -> dict:
    """Published truthfully or not at all."""
    with _lock:
        snap = dict(_last)
    if not snap:
        return {
            "checked": False,
            "note": ("Titan has not audited itself yet. The first check runs on "
                     "the heartbeat shortly after boot."),
            "interval_hours": round(INTERVAL / 3600, 1),
        }
    return {
        "checked": True,
        **snap,
        "interval_hours": round(INTERVAL / 3600, 1),
        "note": ("Titan runs its own audit against its own site with the same "
                 "engine it sells, every "
                 f"{round(INTERVAL / 3600, 1)} hours. The score is published "
                 "as measured — if it regresses, this number falls in public."),
    }


def cycle() -> Optional[dict]:
    """Heartbeat entry point. Never raises."""
    try:
        return audit_self()
    except Exception:
        return None
