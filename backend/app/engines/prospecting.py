"""Find real businesses to sell to, as CRM records rather than prose.

`/api/leads/find` already searched the web, but it handed the results to an LLM
and returned a paragraph. A paragraph cannot be audited, cannot be deduped, and
cannot be worked through — it has to be re-read and re-typed by hand every time.
This turns the same search into structured leads that the existing pipeline can
act on: discover → audit their site → draft outreach citing what was found.

The whole value is in what gets thrown away.

**Directories are not leads.** Searching "leather manufacturers Sialkot" returns
Alibaba, Yellow Pages, TripAdvisor, Facebook and Wikipedia long before it
returns a manufacturer. Those are listings *about* businesses, not businesses.
Filing them as leads produces a CRM full of entries nobody can sell to, and
worse, Titan would then audit `alibaba.com` and draft outreach about Alibaba's
SEO. The blocklist below is the difference between a useful pipeline and junk.

**Deduplication is by registrable domain, not by URL.** The same company
appears as `example.com`, `www.example.com/about` and `example.com/contact`
across one search. Three leads for one business wastes the audit quota and
makes the funnel lie about how many prospects exist.

**Nothing here invents a business.** Every candidate comes from a search result
that was actually returned. With no `TAVILY_API_KEY` this reports that plainly
and returns nothing, rather than asking an LLM to imagine plausible companies —
a hallucinated prospect wastes a real crawl and an hour of Abdullah's day.
"""

from __future__ import annotations

import re
from typing import Optional

from . import research

# Hosts that are directories, marketplaces, social networks or reference sites.
# A hit here is never the business being searched for.
BLOCKED_HOSTS = frozenset({
    "alibaba.com", "aliexpress.com", "amazon.com", "ebay.com", "etsy.com",
    "indiamart.com", "made-in-china.com", "tradeindia.com", "exportersindia.com",
    "yelp.com", "yellowpages.com", "tripadvisor.com", "trustpilot.com",
    "facebook.com", "instagram.com", "twitter.com", "x.com", "linkedin.com",
    "pinterest.com", "tiktok.com", "youtube.com", "reddit.com",
    "wikipedia.org", "wikiwand.com", "quora.com", "medium.com",
    "google.com", "bing.com", "maps.google.com", "goo.gl",
    "crunchbase.com", "glassdoor.com", "indeed.com", "zillow.com",
    "booking.com", "expedia.com", "justdial.com", "sulekha.com",
    "clutch.co", "upwork.com", "fiverr.com", "github.com",
})

# Path fragments that mark a listing page even on an allowed host.
#
# The second group is the subtle one, and it was found by running a real
# search: leatherworkinggroup.com/get-involved/our-community/certified-
# suppliers/sheikh-of-sialkot is a certification body's profile page ABOUT a
# manufacturer. The title is the manufacturer, the domain is the certifier.
# Filed as a lead it would make Titan audit the certifier's website and email
# them about somebody else's business. Any path that names a third party is
# a page about a company, not the company.
BLOCKED_PATH_HINTS = (
    "/search", "/directory", "/listing", "/category",
    "/tag/", "/blog/", "/news/", "/article",
    "/certified-", "/suppliers/", "/supplier/", "/members/", "/member/",
    "/company/", "/companies/", "/profile/", "/get-involved",
)

_WWW = re.compile(r"^www\d*\.", re.I)
# Trailing marketing noise that makes a business name unusable in a greeting.
_TITLE_NOISE = re.compile(
    r"\s*[|\-–—:·]\s*(home|official site|official website|welcome.*|"
    r"best .*|top \d+.*|contact us|about us|shop online.*)\s*$", re.I)
# A listicle headline is never a company name. "Top 5 Best Leather Goods
# Manufacturers in Sialkot" is an article title that happened to rank.
_LISTICLE = re.compile(r"^\s*(top|best|the)\s+(\d+|best|top)\b", re.I)
# Keyword-stuffed titles separated by a lowercase L standing in for a pipe —
# "Manufacturer l Leather Jackets l Leather Goods l Promotional". Real, and
# common enough on export-trade sites that it survived the pipe rule.
_L_SEPARATED = re.compile(r"\s+l\s+")
# Category words that survive splitting a keyword-stuffed title and leave a
# name nobody can be greeted by. "Hi Manufacturer," is no better than the
# stuffed title it came from.
_GENERIC_NAMES = frozenset({
    "manufacturer", "manufacturers", "supplier", "suppliers", "exporter",
    "exporters", "home", "welcome", "products", "product", "shop", "store",
    "contact", "about", "about us", "official website", "index",
    "leather", "leather goods", "wholesale", "company", "services",
})


def registrable(url: str) -> str:
    """Host without a www prefix. Cheap, and enough to dedupe one search."""
    try:
        from urllib.parse import urlparse
        host = (urlparse(url).hostname or "").lower()
        return _WWW.sub("", host)
    except Exception:
        return ""


def is_blocked(url: str) -> bool:
    host = registrable(url)
    if not host:
        return True
    if host in BLOCKED_HOSTS:
        return True
    # Cover regional variants: alibaba.co.uk, amazon.de, facebook.com.pk.
    for b in BLOCKED_HOSTS:
        stem = b.split(".")[0]
        if host == stem or host.startswith(stem + ".") or f".{stem}." in host:
            return True
    low = url.lower()
    return any(h in low for h in BLOCKED_PATH_HINTS)


def _from_domain(host: str) -> str:
    """"triad-thread.pk" → "Triad Thread". Beats a 90-character SEO title and
    beats greeting nobody."""
    stem = host.split(".")[0] if host else ""
    return stem.replace("-", " ").replace("_", " ").title() or "Unknown business"


def clean_name(title: str, host: str) -> str:
    """A name that can open an email without sounding like a search result.

    The bar is deliberately "would Abdullah send this?" — a greeting reading
    "Hi Manufacturer l Leather Jackets l Leather Goods l Promotional ...,"
    loses the deal in the first line, so anything that fails falls back to the
    domain, which is always at least plausible.
    """
    raw = (title or "").strip()
    if _LISTICLE.match(raw):
        return _from_domain(host)

    name = _TITLE_NOISE.sub("", raw)
    # Split on real separators first, then on the lowercase-L stand-in.
    name = name.split(" | ")[0].split(" - ")[0].split(" — ")[0].strip()
    name = _L_SEPARATED.split(name)[0].strip()
    # A keyword-stuffed fragment is not a name either.
    if len(name) < 2 or len(name) > 46 or name.count(",") >= 2:
        return _from_domain(host)
    if name.strip().lower() in _GENERIC_NAMES:
        return _from_domain(host)
    return name[:80]


def discover(query: str, limit: int = 8,
             known_domains: Optional[set[str]] = None) -> dict:
    """Search the live web and return business candidates, not prose."""
    query = (query or "").strip()
    if not query:
        return {"ok": False, "reason": "A search query is required.",
                "candidates": [], "live": False}

    if not research.available():
        return {
            "ok": False,
            "live": False,
            "candidates": [],
            "reason": ("No TAVILY_API_KEY is set, so there is nothing to "
                       "search. Nothing is invented here — an imagined "
                       "prospect wastes a real crawl and an hour of your day. "
                       "A free key at tavily.com allows ~1,000 searches a "
                       "month."),
        }

    # Over-fetch: most results are directories and get dropped.
    results = research.search(query, max_results=max(limit * 3, 12))
    known = {d.lower() for d in (known_domains or set())}

    candidates: list[dict] = []
    seen: set[str] = set()
    rejected = {"directory": 0, "duplicate": 0, "already_known": 0}

    for r in results:
        url = r.get("url", "")
        host = registrable(url)
        if not host or is_blocked(url):
            rejected["directory"] += 1
            continue
        if host in seen:
            rejected["duplicate"] += 1
            continue
        if host in known:
            rejected["already_known"] += 1
            seen.add(host)
            continue
        seen.add(host)
        candidates.append({
            "name": clean_name(r.get("title", ""), host),
            "website": f"https://{host}",
            "domain": host,
            "why": (r.get("content", "") or "")[:220],
            "source_url": url,
        })
        if len(candidates) >= limit:
            break

    return {
        "ok": bool(candidates),
        "live": True,
        "query": query,
        "candidates": candidates,
        "examined": len(results),
        "rejected": rejected,
        "reason": "" if candidates else (
            "The search returned results, but every one was a directory, a "
            "duplicate, or a business already in your CRM. Try a narrower "
            "query — a town and a trade works better than an industry alone."),
        "note": ("Directories, marketplaces and social profiles are dropped: "
                 "they are listings about businesses, not businesses, and "
                 "auditing one would produce outreach about Alibaba's SEO. "
                 "Deduplication is by domain, so one company cannot occupy "
                 "three slots in the funnel."),
    }
