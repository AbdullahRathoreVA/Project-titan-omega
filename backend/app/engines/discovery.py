"""Discovery — Titan finding work nobody told it about.

The opportunity engine scores a hardcoded seed pool. That pool was written once,
by hand, so Titan can only ever rank ideas someone already had. Aether solved
the same problem by mining live data for niches outside its configured list;
this is the equivalent for a service business.

Two sources, both grounded in real client data rather than imagination:

1. CLIENT GAPS. Every audit produces findings. If four clients all lack
   LocalBusiness schema, that is not four tickets — it is one productised
   offer worth selling to all of them and to every future client. This turns
   accumulated audit output into revenue opportunities automatically.

2. PORTFOLIO GAPS. Trials expiring without conversion, clients who have never
   logged in, businesses with no website on file. These are the things that
   quietly lose money and that nobody notices until the client churns.

Everything produced here is evidence-backed: each opportunity names the exact
clients it came from and how many. No invented market research.
"""

from __future__ import annotations

import time
from collections import Counter
from typing import Optional

from ..core import clients
from . import client_seo

# What a recurring finding is actually worth selling as, and roughly what for.
# Prices are conservative one-off figures for a small local business in EUR.
PRODUCTISED = {
    "local_business": {
        "offer": "Local business schema setup",
        "price": 180,
        "pitch": ("Adds Restaurant/LocalBusiness structured data with address, "
                  "hours, cuisine and menu. Feeds Google Maps, the local pack "
                  "and AI answer engines — the single highest-leverage markup "
                  "for a local business."),
        "effort": "1-2 hours",
    },
    "schema": {
        "offer": "Structured data implementation",
        "price": 150,
        "pitch": ("Only ~17% of sites have schema, and it is how AI search "
                  "decides what to quote. Without it the business is close to "
                  "invisible to AI answers."),
        "effort": "1-2 hours",
    },
    "imprint": {
        "offer": "Legal compliance fix (imprint + privacy)",
        "price": 220,
        "pitch": ("Missing imprint is a fine risk and, in Germany, an open "
                  "invitation for a competitor cease-and-desist. This is legal "
                  "exposure, not an SEO nicety."),
        "effort": "1-2 hours",
        "urgent": True,
    },
    "privacy": {
        "offer": "Privacy notice + cookie consent",
        "price": 240,
        "pitch": ("Trackers loading before consent is the most commonly fined "
                  "GDPR defect. Includes a consent manager that blocks "
                  "non-essential scripts until opt-in."),
        "effort": "2-3 hours",
        "urgent": True,
    },
    "cookie_consent": {
        "offer": "Consent manager installation",
        "price": 190,
        "pitch": "Blocks analytics and marketing scripts until the visitor opts in.",
        "effort": "1-2 hours",
        "urgent": True,
    },
    "images_alt": {
        "offer": "Image SEO pass",
        "price": 120,
        "pitch": ("For a restaurant the food photography is the product. "
                  "Unlabelled images cannot rank in image search."),
        "effort": "1 hour",
    },
    "meta_description": {
        "offer": "Search snippet rewrite",
        "price": 90,
        "pitch": ("The text searchers read before clicking, and what AI answer "
                  "engines often lift verbatim."),
        "effort": "45 minutes",
    },
    "sitemap": {
        "offer": "Sitemap + robots setup",
        "price": 80,
        "pitch": "Search engines find and refresh pages faster.",
        "effort": "30 minutes",
    },
    "https": {
        "offer": "HTTPS migration",
        "price": 160,
        "pitch": ("Browsers mark HTTP sites 'Not secure', which destroys trust "
                  "and conversion. Trust is now the primary filter for AI "
                  "citation."),
        "effort": "1-2 hours",
        "urgent": True,
    },
    "og": {
        "offer": "Social sharing preview setup",
        "price": 70,
        "pitch": ("Links shared to WhatsApp or Instagram currently show no "
                  "image or title — for a restaurant that is most sharing."),
        "effort": "30 minutes",
    },
}


def scan_client_gaps(audit_cache: Optional[dict] = None,
                     live: bool = False) -> list[dict]:
    """Recurring findings across all clients, turned into sellable offers.

    live=True re-audits every client (slow, network-bound). Otherwise it uses
    whatever was passed in, so a caller can batch audits on its own schedule.
    """
    audits = dict(audit_cache or {})

    if live:
        for c in clients.all_clients():
            site = c.get("website")
            if not site:
                continue
            audits[c["id"]] = client_seo.audit(
                site, business_name=c.get("business_name", ""),
                city=c.get("city", ""), country=c.get("country", ""))

    counts: Counter = Counter()
    who: dict[str, list[str]] = {}

    for cid, a in audits.items():
        if not a or not a.get("ok"):
            continue
        name = (clients.get(cid) or {}).get("business_name", cid)
        seen = set()
        for f in a.get("findings", []):
            fid = f.get("id")
            if fid in PRODUCTISED and fid not in seen:
                seen.add(fid)
                counts[fid] += 1
                who.setdefault(fid, []).append(name)

    out = []
    for fid, n in counts.most_common():
        p = PRODUCTISED[fid]
        out.append({
            "id": f"gap:{fid}",
            "source": "client audits",
            "offer": p["offer"],
            "affected": n,
            "clients": who[fid],
            "unit_price_eur": p["price"],
            "total_eur": p["price"] * n,
            "effort": p["effort"],
            "pitch": p["pitch"],
            "urgent": bool(p.get("urgent")),
            # Evidence, not a guess: this many clients demonstrably have it.
            "evidence": f"found on {n} of {len(audits)} audited client site(s)",
        })

    out.sort(key=lambda o: (not o["urgent"], -o["total_eur"]))
    return out


def scan_portfolio_risks() -> list[dict]:
    """Things quietly losing money that nobody is watching."""
    rows = clients.all_clients()
    now = time.time()
    risks = []

    ending = [c for c in rows if 0 < c["trial_days_left"] <= 14]
    if ending:
        risks.append({
            "id": "risk:trials",
            "severity": "high",
            "title": f"{len(ending)} trial(s) ending within 14 days",
            "detail": ", ".join(
                f"{c['business_name']} ({c['trial_days_left']}d)" for c in ending),
            "action": ("Send the report and a renewal price before it lapses. "
                       "A trial that expires silently is a lost client."),
        })

    lapsed = [c for c in rows if c["trial_expired"]]
    if lapsed:
        risks.append({
            "id": "risk:expired",
            "severity": "critical",
            "title": f"{len(lapsed)} expired trial(s) still on the books",
            "detail": ", ".join(c["business_name"] for c in lapsed),
            "action": "Convert, extend, or remove them so the numbers stay honest.",
        })

    never = [c for c in rows if not c.get("last_login")]
    if never:
        risks.append({
            "id": "risk:never_logged_in",
            "severity": "high",
            "title": f"{len(never)} client(s) have never signed in",
            "detail": ", ".join(c["business_name"] for c in never),
            "action": ("They cannot value what they have not seen. Walk them "
                       "through the portal or send the PDF directly."),
        })

    nosite = [c for c in rows if not c.get("website")]
    if nosite:
        risks.append({
            "id": "risk:no_website",
            "severity": "medium",
            "title": f"{len(nosite)} client(s) have no website on file",
            "detail": ", ".join(c["business_name"] for c in nosite),
            "action": ("Nothing can be audited without it — and a business with "
                       "no site at all is a website build, the largest sale "
                       "available here."),
        })

    idle = [c for c in rows
            if c.get("metrics", {}).get("seo_audits", 0) == 0
            and c.get("website")]
    if idle:
        risks.append({
            "id": "risk:no_work_done",
            "severity": "high",
            "title": f"{len(idle)} paying client(s) with no work logged",
            "detail": ", ".join(c["business_name"] for c in idle),
            "action": "Run their audit now. An empty activity log ends a trial.",
        })

    order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    risks.sort(key=lambda r: order.get(r["severity"], 9))
    return risks


def report(audit_cache: Optional[dict] = None, live: bool = False) -> dict:
    gaps = scan_client_gaps(audit_cache, live=live)
    risks = scan_portfolio_risks()
    return {
        "opportunities": gaps,
        "risks": risks,
        "pipeline_value_eur": sum(g["total_eur"] for g in gaps),
        "urgent_value_eur": sum(g["total_eur"] for g in gaps if g["urgent"]),
        "clients": len(clients.all_clients()),
        "scanned_at": time.time(),
        "note": ("Every opportunity here is derived from findings on real "
                 "client sites, and names which clients. Nothing is projected "
                 "or estimated from market data."),
    }
