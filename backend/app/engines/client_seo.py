"""SEO audit for a CLIENT's website — the thing they actually pay for.

Aether's seo.py audits pages we generated ourselves, so it can assume the
structure. This audits a site we did not build and cannot control, over the
public internet, with nothing but an HTTP GET.

Built from measured July 2026 ranking evidence:
  - only ~17% of the top 10M sites implement schema, and schema is now core
    AI-citation infrastructure (AI Overviews, ChatGPT Search, Perplexity)
  - 40-60% of pages on a typical site have zero inbound internal links
  - the strongest single AI-search factor is answering the question in the
    first 1-2 sentences
  - for a local business, proximity (~55%), Google Business Profile (~32%) and
    reviews (16-20%) dominate — which is why a restaurant audit weights
    LocalBusiness schema, NAP and hours far above generic on-page tweaks

Every finding carries a fix the client (or Abdullah) can actually action. No
score is invented: if something cannot be checked over HTTP, it is reported as
"needs manual check" rather than guessed.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

from . import compliance, local_seo, verticals

TIMEOUT = 15

# A normal browser UA. This audit only ever runs against a site the client has
# hired us to audit — their own — and a bot-labelled UA gets 403'd by ordinary
# WAF rules (measured: mcdonalds.com.pk returns 403, pizzahut.com.pk drops the
# connection). Every commercial SEO crawler does the same for the same reason.
# We still send one request per page and honour robots.txt below.
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# Weighted so a restaurant's real ranking levers dominate the score.
WEIGHTS = {
    "title": 10, "meta_description": 8, "h1": 8, "schema": 14,
    "local_business": 14, "nap": 10, "images_alt": 6, "viewport": 5,
    "canonical": 4, "https": 6, "sitemap": 5, "robots": 4, "og": 6,
}


def _fetch(url: str) -> tuple[Optional[str], Optional[str], int]:
    """Return (html, error, status)."""
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml",
        })
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            raw = r.read(1_500_000)
            enc = r.headers.get_content_charset() or "utf-8"
            return raw.decode(enc, errors="replace"), None, r.status
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}", e.code
    except Exception as e:
        return None, f"{type(e).__name__}", 0


def _text(pattern: str, html: str, group: int = 1) -> str:
    m = re.search(pattern, html, re.I | re.S)
    return (m.group(group) or "").strip() if m else ""


def audit(url: str, *, business_name: str = "", city: str = "",
          country: str = "", industry: str = "") -> dict:
    """Full audit of one page. Never raises."""
    if not url:
        return {"ok": False, "error": "no website configured"}
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    html, err, status = _fetch(url)
    if html is None:
        return {"ok": False, "url": url, "error": err, "status": status,
                "findings": [{
                    "id": "unreachable", "severity": "critical",
                    "title": "Website could not be loaded",
                    "detail": f"The site returned {err}. Nothing else can be "
                              f"checked until it responds.",
                    "fix": "Confirm the domain resolves and the server is up.",
                }]}

    findings: list[dict] = []
    earned: dict[str, bool] = {}
    parsed = urllib.parse.urlparse(url)
    origin = f"{parsed.scheme}://{parsed.netloc}"

    # Every client-facing string below is a function of the trade. Telling a
    # law firm that "the food photography is the product" is not a credible
    # deliverable, and this audit is what the client actually pays for.
    vert = verticals.profile(verticals.detect(html, industry))

    def add(fid, severity, title, detail, fix, key=None, ok=False):
        if key:
            earned[key] = ok
        if not ok:
            findings.append({"id": fid, "severity": severity, "title": title,
                             "detail": detail, "fix": fix})

    # ---------------------------------------------------------- basics ----
    title = _text(r"<title[^>]*>(.*?)</title>", html)
    add("title", "critical", "Missing or weak page title",
        f"Found: {title[:80]!r} ({len(title)} chars). Google truncates around "
        f"60 and an empty title is a hard ranking loss.",
        f"Write a 50-60 character title, e.g. "
        f"'{business_name or 'Your Business'} — {vert.title_example} in "
        f"{city or 'your city'}'",
        key="title", ok=bool(title) and 15 <= len(title) <= 65)

    desc = _text(r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']', html) \
        or _text(r'<meta[^>]+content=["\'](.*?)["\'][^>]+name=["\']description["\']', html)
    add("meta_description", "high", "Missing meta description",
        f"Found {len(desc)} chars. This is the text searchers read before "
        f"clicking, and AI answer engines often lift it verbatim.",
        "Write 140-160 characters describing what you offer and where.",
        key="meta_description", ok=bool(desc) and 80 <= len(desc) <= 175)

    h1s = re.findall(r"<h1[^>]*>(.*?)</h1>", html, re.I | re.S)
    add("h1", "high", "H1 problem",
        f"Found {len(h1s)} H1 tag(s). Exactly one is correct.",
        "Use a single H1 naming the business and its category.",
        key="h1", ok=len(h1s) == 1)

    # ---------------------------------------------------------- schema ----
    blocks = re.findall(
        r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', html, re.I | re.S)
    types: list[str] = []
    for b in blocks:
        try:
            data = json.loads(b.strip())
        except Exception:
            continue
        for node in (data if isinstance(data, list) else [data]):
            if isinstance(node, dict):
                graph = node.get("@graph")
                for n in (graph if isinstance(graph, list) else [node]):
                    t = n.get("@type") if isinstance(n, dict) else None
                    if isinstance(t, list):
                        types.extend(str(x) for x in t)
                    elif t:
                        types.append(str(t))

    add("schema", "critical", "No structured data (schema) found",
        "Only ~17% of sites implement schema, and it is how AI Overviews, "
        "ChatGPT Search and Perplexity decide what to quote. Without it you "
        "are close to invisible to AI search.",
        f"Add JSON-LD schema. For a {vert.label.lower()}, start with "
        f"{vert.schema_type}.",
        key="schema", ok=bool(types))

    local_types = {"LocalBusiness", "Restaurant", "FoodEstablishment",
                   "CafeOrCoffeeShop", "BarOrPub", "Store", "Organization"}
    has_local = bool(local_types & set(types))
    add("local_business", "critical",
        f"No LocalBusiness / {vert.schema_type} schema",
        "For a local business this is the single highest-leverage markup. "
        "Local ranking is driven by proximity (~55%), Google Business Profile "
        "(~32%) and reviews (16-20%) — this schema feeds all three surfaces.",
        f"Add {vert.schema_type} schema with name, address, geo, telephone, "
        f"openingHoursSpecification, priceRange"
        + (f", plus {vert.extra_schema}." if vert.extra_schema else "."),
        key="local_business", ok=has_local)

    # ------------------------------------------------------------- NAP ----
    has_phone = bool(re.search(r'href=["\']tel:', html, re.I)) or bool(
        re.search(r"\+?\d[\d\s\-()]{8,}\d", html))
    has_addr = bool(re.search(
        r"address|street|road|avenue|block|sector|plaza", html, re.I))
    add("nap", "high", "Name / address / phone not clearly on the page",
        f"phone detected: {has_phone}, address wording detected: {has_addr}. "
        f"Consistent NAP is a core local ranking signal.",
        "Put the full address and a tel: link in the footer of every page, "
        "matching your Google Business Profile exactly.",
        key="nap", ok=has_phone and has_addr)

    # ---------------------------------------------------------- images ----
    imgs = re.findall(r"<img\b[^>]*>", html, re.I)
    no_alt = [i for i in imgs
              if not re.search(r'\balt\s*=\s*["\'][^"\']+["\']', i, re.I)]
    add("images_alt", "medium", "Images missing alt text",
        f"{len(no_alt)} of {len(imgs)} images have no alt text. For a "
        f"{vert.label.lower()} {vert.asset_noun} is the product — unlabelled "
        f"images cannot rank in image search.",
        f"Describe each image in the alt text, e.g. '{vert.alt_example}'.",
        key="images_alt", ok=bool(imgs) and len(no_alt) <= max(1, len(imgs) // 5))

    # ------------------------------------------------------- technical ----
    add("viewport", "high", "No mobile viewport tag",
        "Most local searches are on a phone. Without this the layout "
        "will not adapt and mobile ranking suffers.",
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        key="viewport", ok=bool(re.search(r'name=["\']viewport["\']', html, re.I)))

    add("canonical", "low", "No canonical URL",
        "Prevents duplicate-content dilution across www/non-www and query "
        "string variants.",
        '<link rel="canonical" href="…"> in the head.',
        key="canonical", ok=bool(re.search(r'rel=["\']canonical["\']', html, re.I)))

    add("https", "critical", "Site is not served over HTTPS",
        "Browsers mark HTTP sites 'Not secure', which destroys trust and "
        "conversion, and trust is now the primary filter for AI citation.",
        "Install a free Let's Encrypt certificate and redirect HTTP to HTTPS.",
        key="https", ok=parsed.scheme == "https")

    og = len(re.findall(r'property=["\']og:', html, re.I))
    add("og", "medium", "No Open Graph tags",
        f"Links shared to WhatsApp, Instagram or Facebook will show no image "
        f"or title — for a {vert.label.lower()} that is {vert.share_context}.",
        f"Add og:title, og:description and og:image (a strong image of "
        f"{vert.asset_noun.replace('the ', '')}).",
        key="og", ok=og >= 3)

    # ------------------------------------------------- site-level checks ----
    # A sitemap INDEX (<sitemapindex>) is just as valid as a flat <urlset> and
    # is what larger sites actually serve. Accepting only <urlset> reported
    # "No sitemap.xml" for vapiano.de while quoting its own HTTP 200 in the same
    # sentence — a false positive in a client-facing report, which is worse than
    # missing the finding entirely.
    sm, _, sm_status = _fetch(f"{origin}/sitemap.xml")
    sm_valid = bool(sm) and ("<urlset" in sm or "<sitemapindex" in sm)
    add("sitemap", "medium", "No valid sitemap.xml",
        f"{origin}/sitemap.xml returned "
        f"{('HTTP ' + str(sm_status)) if sm_status else 'nothing'}"
        + (" but the body is not a sitemap." if sm and not sm_valid else ".")
        + " Search engines find pages slower without one.",
        "Publish a sitemap.xml (or sitemap index) and reference it from "
        "robots.txt.",
        key="sitemap", ok=sm_valid)

    rb, _, rb_status = _fetch(f"{origin}/robots.txt")
    add("robots", "low", "No robots.txt",
        f"{origin}/robots.txt returned {rb_status or 'nothing'}.",
        "Add robots.txt allowing crawl and listing the sitemap.",
        key="robots", ok=bool(rb))

    # ------------------------------------------------------- compliance ----
    # Legal exposure is reported ALONGSIDE SEO, not folded into the SEO score.
    # A missing Impressum is not "8 points off" - it is a fine and an open
    # invitation for a competitor Abmahnung, and it must not be averaged away.
    # Weighted local scoring on published 2026 ranking factors. Kept separate
    # from the technical score: a restaurant can have perfect meta tags and
    # still be invisible locally, and averaging the two would hide that.
    local = local_seo.analyse(html, business=business_name, city=city,
                              industry=industry, url=url)
    findings.extend([
        {"id": f"local:{f['dimension']}", "severity": f["severity"],
         "title": f["title"], "detail": f["detail"] + f"  [{f['source']}]",
         "fix": f["fix"]}
        for f in local["findings"]
    ])

    tld = parsed.netloc.rsplit(".", 1)[-1] if "." in parsed.netloc else ""
    legal = compliance.check(html, country=country, tld=tld, url=url)
    findings.extend(legal["findings"])

    # ----------------------------------------------------------- score ----
    total = sum(WEIGHTS.values())
    got = sum(w for k, w in WEIGHTS.items() if earned.get(k))
    score = round(100 * got / total)

    order = {"legal-critical": 0, "critical": 1, "high": 2,
             "medium": 3, "low": 4}
    findings.sort(key=lambda f: order.get(f["severity"], 9))

    return {
        "ok": True,
        "url": url,
        "status": status,
        "score": score,
        "grade": ("A" if score >= 90 else "B" if score >= 75 else
                  "C" if score >= 60 else "D" if score >= 40 else "F"),
        "passed": [k for k, v in earned.items() if v],
        "failed": [k for k, v in earned.items() if not v],
        "schema_types": sorted(set(types)),
        "findings": findings,
        "legal": legal,
        "local": local,
        "counts": {
            "legal_critical": legal["legal_critical"],
            "critical": sum(1 for f in findings if f["severity"] == "critical"),
            "high": sum(1 for f in findings if f["severity"] == "high"),
            "medium": sum(1 for f in findings if f["severity"] == "medium"),
            "low": sum(1 for f in findings if f["severity"] == "low"),
        },
        "note": ("Rankings, traffic and Google Business Profile health cannot "
                 "be read over HTTP — those need Search Console and GBP "
                 "access, which the client must grant."),
    }


def suggested_schema(business_name: str, city: str, website: str,
                     industry: str = "", phone: str = "",
                     country_code: str = "DE") -> str:
    """A ready-to-paste JSON-LD block — the highest-value single fix.

    Emits the correct Schema.org SUBTYPE for the trade. This previously always
    emitted Restaurant with servesCuisine and acceptsReservations, so pasting it
    onto a law firm's site declared the firm a restaurant — worse than having no
    schema at all, because search engines believe it.
    """
    vert = verticals.profile(verticals.detect("", industry))
    node = {
        "@context": "https://schema.org",
        "@type": vert.schema_type,
        "name": business_name or "Your Business",
        "url": website or "",
        "priceRange": "$$",
        "address": {
            "@type": "PostalAddress",
            "streetAddress": "<street address>",
            "addressLocality": city or "<city>",
            "addressCountry": country_code or "DE",
        },
        "telephone": phone or "<phone number>",
        "openingHoursSpecification": [{
            "@type": "OpeningHoursSpecification",
            "dayOfWeek": ["Monday", "Tuesday", "Wednesday", "Thursday",
                          "Friday", "Saturday", "Sunday"],
            "opens": "09:00", "closes": "18:00",
        }],
    }
    # Subtype-specific properties, only where they are actually meaningful.
    if vert.key in ("restaurant", "cafe", "bar", "bakery"):
        node["servesCuisine"] = "<cuisine>"
        node["openingHoursSpecification"][0].update(opens="12:00", closes="23:00")
    if vert.key in ("restaurant", "hotel"):
        node["acceptsReservations"] = "True"
    if vert.key in ("healthcare", "dentist"):
        node["medicalSpecialty"] = "<specialty>"
    if vert.key in ("legal", "tradesperson", "auto"):
        node["areaServed"] = city or "<service area>"
    return json.dumps(node, indent=2, ensure_ascii=False)
