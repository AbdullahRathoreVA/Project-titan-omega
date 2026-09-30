"""Titan audits its own website with the same engine it sells.

- An SEO product that scores badly on its own SEO is an easy objection. The
  site was missing a sitemap and JSON-LD, the two things the engine flags as
  critical for clients; those are generated here.
- It's a trust signal anyone can check: "Titan scores 94/100 on its own
  audit, re-checked every 6 hours, and here are the open findings" can be
  verified in seconds, because the same code produced it.

The score is published as measured. If the site regresses, the public number
goes down; a hardcoded 100 would be found out by the first prospect who ran
another audit.

Runs on the existing heartbeat - no new process, no new cost.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Optional

from ..core import events
from . import client_seo

# The public origin. Overridable so a fork doesn't audit this domain.
SITE = os.getenv("TITAN_PUBLIC_URL", "https://titanomega-ai.com").rstrip("/")

# Six hours: often enough to catch a regression the day it ships, rarely
# enough that Titan isn't a noticeable share of its own traffic.
INTERVAL = float(os.getenv("TITAN_SELF_SEO_INTERVAL", str(6 * 3600)))

# Pages worth listing and auditing. Everything else is behind a login and
# doesn't belong in a sitemap.
PUBLIC_PATHS = (
    ("/", 1.0, "daily"),
    ("/pricing", 0.9, "weekly"),
    # The sign-up page, the second most valuable URL after the homepage.
    ("/join", 0.9, "weekly"),
    ("/privacy", 0.3, "yearly"),
    ("/terms", 0.3, "yearly"),
    ("/refunds", 0.3, "yearly"),
    ("/portal", 0.4, "monthly"),
)

_lock = threading.RLock()
_last: dict = {}
_last_run = 0.0


def sitemap_xml() -> str:
    """A real sitemap. Titan's audit flags a missing one on client sites."""
    today = time.strftime("%Y-%m-%d", time.gmtime())
    # The landing pages are the content a search engine can actually match
    # queries against, so they belong in the sitemap.
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

    Disallowing /api matters: indexed JSON endpoints cause confusion, and the
    client portal must never appear in search results.
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

    Titan tells clients that schema is how AI Overviews and ChatGPT Search
    decide what to quote, so its own site publishes it too. Offers come from
    the real plan table so the marked-up price can't drift from what's charged.
    """
    from ..core import billing, contact

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
                    "Your AI business command centre: lead finding and CRM, "
                    "posts with images, a voice assistant in 12 languages, "
                    "market scans, Job Radar, revenue tracking, and 24/7 "
                    "website SEO and legal checks. Start free."),
                "featureList": [
                    "Lead finding and CRM pipeline",
                    "Social post drafts with images and a ready-to-post queue",
                    "Ask Titan by voice or text in 12 languages",
                    "Market scan and Job Radar",
                    "Revenue and expense tracking",
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
                # Empty until real details are set; never a placeholder. Schema alone wouldn't
                # pass Titan's own NAP check either - that reads visible text, which is
                # `contact.html_block`.
                **contact.schema_fragment(),
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
    """Published as measured, or not at all."""
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
