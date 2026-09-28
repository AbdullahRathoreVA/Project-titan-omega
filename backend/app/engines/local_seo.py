"""Local SEO scoring based on published ranking-factor studies.

client_seo.py checks whether markup exists; this scores what moves a local
business in search, using published weights:

  proximity to searcher      55.2%  (Search Atlas ML study)
  Google Business Profile    32%    (Whitespark 2026)
  review signals            ~20%    (Whitespark 2026, up from 16%)
  dedicated service pages    top local organic and AI visibility factor

Two findings shape the advice:

1. AI assistants now drive local recommendations. ChatGPT doesn't read Google
   Business Profile; it draws on the Bing index, Yelp, TripAdvisor and Reddit,
   so claiming Bing Places matters for appearing in AI answers.
2. Recent reviews beat review count: rankings drop after about three weeks
   without a new review (Sterling Sky).

Every result names its source and says what can't be measured from outside
the site.
"""

from __future__ import annotations

import json
import re
from typing import Optional

# Published weights, normalised to 100.
DIMENSIONS = {
    "gbp": {"weight": 25, "label": "Google Business Profile signals"},
    "reviews": {"weight": 20, "label": "Reviews and reputation"},
    "onpage": {"weight": 20, "label": "Local on-page SEO"},
    "nap": {"weight": 15, "label": "NAP consistency"},
    "schema": {"weight": 10, "label": "Local schema markup"},
    "authority": {"weight": 10, "label": "Local authority signals"},
}

# Vertical-specific data lives in engines/verticals.py (one source, so the
# schema and signal lists can't drift apart).
from . import verticals as _verticals   # noqa: E402

VERTICAL_SCHEMA = _verticals.VERTICAL_SCHEMA
VERTICAL_SIGNALS = _verticals.VERTICAL_SIGNALS
detect_vertical = _verticals.detect


def _schema_nodes(html: str) -> list[dict]:
    out: list[dict] = []
    for block in re.findall(
            r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>',
            html or "", re.I | re.S):
        try:
            data = json.loads(block.strip())
        except Exception:
            continue
        for node in (data if isinstance(data, list) else [data]):
            if not isinstance(node, dict):
                continue
            graph = node.get("@graph")
            out.extend(g for g in (graph if isinstance(graph, list) else [node])
                       if isinstance(g, dict))
    return out


def analyse(html: str, *, business: str = "", city: str = "",
            industry: str = "", url: str = "") -> dict:
    """Score the six local dimensions. Never raises."""
    html = html or ""
    low = html.lower()
    vertical = detect_vertical(html, industry)
    nodes = _schema_nodes(html)
    types = {str(n.get("@type")) for n in nodes if n.get("@type")}

    scores: dict[str, float] = {}
    findings: list[dict] = []

    def add(dim: str, earned: float, severity: str, title: str,
            detail: str, fix: str, source: str = ""):
        scores[dim] = earned
        if earned < 1.0:
            findings.append({"dimension": dim, "severity": severity,
                             "title": title, "detail": detail, "fix": fix,
                             "source": source})

    # ---------------------------------------------------------------- GBP --
    has_map = bool(re.search(r"google\.com/maps|maps\.google|place_id", low))
    has_hours = bool(re.search(r"openinghours|opening_hours|öffnungszeiten|"
                               r"opening hours|mon|montag", low))
    gbp = (0.5 if has_map else 0) + (0.5 if has_hours else 0)
    add("gbp", gbp, "critical" if gbp < 0.5 else "high",
        "Weak Google Business Profile integration",
        f"Map embed: {has_map}. Opening hours on page: {has_hours}. GBP signals "
        f"carry ~32% of local pack weight, and businesses open at search time "
        f"rank higher.",
        "Embed the Google Maps listing, publish opening hours on the page, and "
        "confirm the GBP primary category is exact — an incorrect primary "
        "category is the single biggest negative local factor.",
        "Whitespark 2026")

    # ------------------------------------------------------------ reviews --
    agg = next((n for n in nodes if "aggregateRating" in n), None)
    rating = count = 0.0
    if agg:
        r = agg.get("aggregateRating") or {}
        try:
            rating = float(r.get("ratingValue") or 0)
            count = float(r.get("reviewCount") or r.get("ratingCount") or 0)
        except (TypeError, ValueError):
            pass
    rev = 0.0
    if count >= 10:
        rev += 0.5          # Sterling Sky's "magic threshold"
    if rating >= 4.5:
        rev += 0.5          # 31% of consumers only consider 4.5+
    elif rating >= 4.0:
        rev += 0.25
    add("reviews", rev, "high",
        "Review signals not visible to search engines",
        f"aggregateRating in schema: {'yes' if agg else 'no'}"
        + (f" ({rating} stars, {int(count)} reviews)" if agg else "")
        + ". Reviews are ~20% of local ranking, and VELOCITY matters more than "
          "total: rankings drop after roughly 18 days with no new review.",
        "Publish aggregateRating in schema and run a continuous review request "
        "flow — one new review every two weeks beats a large but stale total. "
        "Never pre-screen customers before asking (prohibited by Google and the "
        "FTC).",
        "Whitespark 2026 / Sterling Sky 18-day rule")

    # ------------------------------------------------------------- onpage --
    title = (re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S) or
             [None, ""])[1] if re.search(r"<title", html, re.I) else ""
    h1 = " ".join(re.findall(r"<h1[^>]*>(.*?)</h1>", html, re.I | re.S))
    city_l = (city or "").lower()
    in_title = bool(city_l and city_l in title.lower())
    in_h1 = bool(city_l and city_l in h1.lower())
    has_tel = bool(re.search(r'href=["\']tel:', low))
    onp = (0.4 if in_title else 0) + (0.3 if in_h1 else 0) + (0.3 if has_tel else 0)
    add("onpage", onp, "high",
        "Local intent missing from on-page signals",
        f"City in title: {in_title}. City in H1: {in_h1}. Click-to-call link: "
        f"{has_tel}. Dedicated service pages are the #1 local organic factor "
        f"and the #2 AI visibility factor.",
        f"Put '{city or 'your city'}' in the title and H1, add a tel: link "
        f"above the fold, and give each core offering its own page.",
        "Whitespark 2026")

    # ---------------------------------------------------------------- NAP --
    has_phone = has_tel or bool(re.search(r"\+?\d[\d\s\-()]{8,}\d", html))
    addr_node = next((n for n in nodes if isinstance(n.get("address"), dict)), None)
    has_addr_text = bool(re.search(
        r"stra(ss|ß)e|street|avenue|platz|weg|road|\b\d{5}\b", low))
    nap = (0.4 if has_phone else 0) + (0.3 if has_addr_text else 0) \
        + (0.3 if addr_node else 0)
    add("nap", nap, "high",
        "Name / address / phone incomplete or unstructured",
        f"Phone: {has_phone}. Address text: {has_addr_text}. PostalAddress in "
        f"schema: {bool(addr_node)}. Three of the top five AI-visibility factors "
        f"are citation-related, and they all depend on consistent NAP.",
        "Show the full address and a tel: link in the footer of every page, and "
        "mirror them exactly in PostalAddress schema and on Google, Bing, Yelp "
        "and Apple Maps. Any mismatch weakens all of them.",
        "Whitespark 2026")

    # ------------------------------------------------------------- schema --
    want = VERTICAL_SCHEMA.get(vertical, "LocalBusiness")
    has_correct = want in types
    has_generic = "LocalBusiness" in types and not has_correct
    geo_ok = any(isinstance(n.get("geo"), dict) for n in nodes)
    menu_ok = vertical != "restaurant" or any(
        t in types for t in ("Menu", "MenuSection", "MenuItem"))
    sch = (0.5 if has_correct else (0.2 if has_generic else 0)) \
        + (0.25 if geo_ok else 0) + (0.25 if menu_ok else 0)
    add("schema", sch, "high",
        f"Schema is not the correct subtype for a {vertical or 'local business'}",
        f"Found: {sorted(types) or 'none'}. Expected '{want}'"
        + (" plus Menu/MenuSection/MenuItem" if vertical == "restaurant" else "")
        + f". Geo coordinates present: {geo_ok}.",
        f"Use '{want}' rather than generic LocalBusiness, add geo coordinates to "
        f"at least five decimal places, openingHoursSpecification, telephone and "
        f"priceRange"
        + (", and mark the menu up with Menu + MenuSection + MenuItem so AI "
           "answer engines can quote individual dishes."
           if vertical == "restaurant" else "."),
        "Schema.org / Google structured data guidance")

    # ---------------------------------------------------------- authority --
    signals = [w for w in ("chamber of commerce", "ihk", "bbb", "tripadvisor",
                           "yelp", "michelin", "gault", "best of", "award",
                           "presse", "press") if w in low]
    auth = min(len(signals) / 3, 1.0)
    add("authority", auth, "medium",
        "Few local authority signals on the page",
        f"Detected: {signals or 'none'}. 'Best of' list placement is the top "
        f"AI-visibility citation factor, and brand mentions correlate about 3x "
        f"more strongly with AI visibility than backlinks (0.664 vs 0.218).",
        "Pursue local press, chamber membership and 'best of' guides, and show "
        "those badges on the site. For a restaurant, TripAdvisor and Michelin/"
        "Gault-Millau listings feed the sources AI assistants actually read.",
        "Whitespark 2026 / Ahrefs correlation study")

    total = sum(DIMENSIONS[d]["weight"] * scores.get(d, 0) for d in DIMENSIONS)
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    findings.sort(key=lambda f: order.get(f["severity"], 9))

    return {
        "score": round(total),
        "vertical": vertical or "unknown",
        "expected_schema": want,
        "dimensions": {
            d: {"label": DIMENSIONS[d]["label"],
                "weight": DIMENSIONS[d]["weight"],
                "earned": round(DIMENSIONS[d]["weight"] * scores.get(d, 0), 1)}
            for d in DIMENSIONS
        },
        "findings": findings,
        "ai_search": {
            "note": ("ChatGPT does NOT read Google Business Profile. It sources "
                     "local answers from the Bing index, Yelp, TripAdvisor and "
                     "Reddit — so Bing Places is how a business appears in AI "
                     "recommendations at all."),
            "why_it_matters": ("45% of consumers now use AI for local "
                               "recommendations, up from 6%, and AI referrals "
                               "convert at 15.9% against 1.76% for Google "
                               "organic."),
            "actions": [
                "Claim and complete Bing Places (feeds ChatGPT, Copilot, Alexa)",
                "Claim Apple Maps / Apple Business",
                "Build presence on TripAdvisor and Yelp",
                "Target 'best of' local lists — the #1 AI citation factor",
            ],
        },
        "cannot_measure": [
            "Proximity to the searcher — 55.2% of local ranking variance and "
            "impossible to influence or measure from the site",
            "Live local-pack position (needs geo-grid rank tracking)",
            "Google Business Profile Insights (needs GBP owner access)",
            "Actual review velocity (needs GBP or third-party API)",
        ],
    }
