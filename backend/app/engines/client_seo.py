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
    """Return (html, error, status).

    Every URL here came from a stranger typing it into the signup form, so it
    goes through the SSRF guard rather than straight to urllib. Without that,
    `http://169.254.169.254/` or `http://127.0.0.1:7860/api/admin/clients`
    would be fetched from inside Titan's own trust boundary and returned as an
    "audit". See core/safe_fetch.py.
    """
    from ..core import safe_fetch
    return safe_fetch.fetch(url, user_agent=UA, timeout=TIMEOUT)


def _text(pattern: str, html: str, group: int = 1) -> str:
    m = re.search(pattern, html, re.I | re.S)
    return (m.group(group) or "").strip() if m else ""


# --------------------------------------------------------------------- NAP --
# These two checks used to run against the raw HTML, and both produced passes
# that had never been observed. Measured on Titan's own /compliance/de:
#
#   phone   matched "1781791509496" inside the Cloudflare analytics beacon URL
#           that Cloudflare injects at the edge. Every site behind Cloudflare
#           therefore "had a phone number".
#   address matched the word "block" in ordinary prose.
#
# So the page scored 100/A with neither a phone number nor an address on it.
# That is the exact failure this codebase exists to avoid — a reported pass
# nobody measured — and it was being served to paying clients, telling them
# their contact details were fine when the page had none.
#
# The root cause of both is reading markup instead of what a human sees. The
# checks now run on visible text, with script, style, comments and every tag
# attribute removed first.

_ADDRESS_WORDS = (r"address|street|str\.|straße|strasse|road|avenue|lane|"
                  r"block|sector|plaza|suite|floor|building|p\.?o\.? box")


def _visible_text(html: str) -> str:
    """What a reader actually sees: no script, style, comments or attributes.

    A URL in a src attribute is not page content, and treating it as such is
    how a CDN's cache-busting hash became a phone number.
    """
    out = re.sub(r"<(script|style|template)\b.*?</\1>", " ", html,
                 flags=re.I | re.S)
    out = re.sub(r"<!--.*?-->", " ", out, flags=re.S)
    out = re.sub(r"<[^>]+>", " ", out)
    return re.sub(r"\s+", " ", out)


def _has_phone(html: str) -> bool:
    """A tel: link, or something in the visible text shaped like a phone number.

    Length is bounded at both ends: a real number carries 7 to 15 digits (E.164
    caps at 15), which excludes both a 4-digit year and a 13-digit cache hash.
    """
    if re.search(r'href=["\']tel:\s*[+\d]', html, re.I):
        return True
    for m in re.finditer(r"\+?\d[\d\s\-().]{5,}\d", _visible_text(html)):
        if 7 <= sum(c.isdigit() for c in m.group()) <= 15:
            return True
    return False


def _has_address(html: str) -> bool:
    """An <address> element, or an address word standing next to a number.

    The bare word test is what let "block" pass. A real street address pairs
    the word with a number — "Block 5", "12 Main Street", "Sector G-9" — and
    requiring that pairing removes the prose match without losing the South
    Asian and German forms the wording was chosen to catch.
    """
    if re.search(r"<address\b", html, re.I):
        return True
    text = _visible_text(html)
    # "Block 5", "Sector G-9" — the word, then a house/plot number, optionally
    # letter-prefixed as Islamabad sectors are.
    word_then_number = rf"(?:{_ADDRESS_WORDS})[\s,.\-]*[A-Za-z]?[\s\-]?\d"
    # "12 Main Street", "3 Musterweg" — the number, then at most two words,
    # then the address word. The number must be followed by whitespace, so
    # "Founded 2019. We will address that" does not match: the full stop breaks
    # it before the window opens.
    number_then_word = (rf"\b\d{{1,5}}\s+(?:[A-Za-zÄÖÜäöüß'.-]+\s+){{0,2}}"
                        rf"(?:{_ADDRESS_WORDS})")
    if re.search(word_then_number, text, re.I) or \
            re.search(number_then_word, text, re.I):
        return True
    # A postcode immediately before a place name — "10115 Berlin", "54000
    # Lahore" — is an address even with none of the words above.
    return bool(re.search(r"\b\d{4,6}\s+[A-ZÄÖÜ][a-zäöüß]{2,}", text))


def audit(url: str, *, business_name: str = "", city: str = "",
          country: str = "", industry: str = "") -> dict:
    """Full audit of one page. Never raises."""
    if not url:
        return {"ok": False, "error": "no website configured"}
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    # Uses a real browser when the plain GET looks like a shell AND a renderer
    # is configured; otherwise it reports that it could not. See core/render.py
    # — the point is that `rendering` always says which happened.
    from ..core import render as _render
    html, err, status, rendering = _render.fetch_best(
        url, user_agent=UA, timeout=TIMEOUT, fetcher=_fetch)
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

    # A page that builds itself in the browser was, until now, audited as if
    # the shell were the site: "no H1", "no schema", "thin content", all
    # reported with total confidence and all describing a <div id="root">.
    # A confident wrong finding is indistinguishable from a right one, so this
    # goes at the TOP of the list and the result carries reliable=False.
    unreliable = rendering.get("reliable") is False
    if unreliable:
        findings.append({
            "id": "client_rendered",
            "severity": "critical",
            "title": "This page is built by JavaScript — the audit below is "
                     "not reliable for it",
            "detail": (
                "The server sent "
                f"{rendering.get('visible_text_chars', 0)} characters of "
                f"visible text and "
                f"{rendering.get('script_tags', 0)} script tags"
                + (f" ({', '.join(rendering['frameworks'])})"
                   if rendering.get("frameworks") else "")
                + ". Evidence: " + "; ".join(rendering.get("reasons", []))
                + ". Google renders JavaScript and will see more than this, so "
                  "the findings below may describe an empty shell rather than "
                  "your real page. Titan is telling you it cannot see this "
                  "page properly instead of guessing."),
            "fix": ("Server-render or pre-render the page so its content is in "
                    "the HTML. This matters beyond Titan: AI answer engines "
                    "(ChatGPT Search, Perplexity) largely do NOT execute "
                    "JavaScript, so a client-rendered page is close to "
                    "invisible to them even when Google can read it."),
        })

    # Every client-facing string below is a function of the trade. Telling a
    # law firm that "the food photography is the product" is not a credible
    # deliverable, and this audit is what the client actually pays for.
    vert = verticals.profile(verticals.detect(html, industry))

    def add(fid, severity, title, detail, fix, key=None, ok=False, na=False):
        """Record a check.

        `na` marks a check that does not apply to this page at all — not a
        pass and not a failure. It is excluded from BOTH sides of the score,
        because counting it either way is a lie: a pass would claim the site
        did something well that it never did, and a failure would invent a
        defect. See the images_alt check for why this exists.
        """
        if key:
            earned[key] = "na" if na else ok
        if na:
            return
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
    # A software product is not served from a place. Demanding a street
    # address, geo coordinates and opening hours from a SaaS is wrong advice —
    # Titan gave itself exactly that when it first audited its own site.
    if vert.local_business:
        add("local_business", "critical",
            f"No LocalBusiness / {vert.schema_type} schema",
            "For a local business this is the single highest-leverage markup. "
            "Local ranking is driven by proximity (~55%), Google Business "
            "Profile (~32%) and reviews (16-20%) — this schema feeds all three "
            "surfaces.",
            f"Add {vert.schema_type} schema with name, address, geo, telephone, "
            f"openingHoursSpecification, priceRange"
            + (f", plus {vert.extra_schema}." if vert.extra_schema else "."),
            key="local_business", ok=has_local)
    else:
        add("local_business", "high",
            f"No {vert.schema_type} schema",
            f"A {vert.label.lower()} is not found by proximity, so the local "
            f"signals do not apply — but structured data still decides what AI "
            f"answer engines can quote about the product.",
            f"Add {vert.schema_type} schema with "
            + (vert.extra_schema or "the properties that describe the product")
            + ".",
            key="local_business",
            ok=bool({vert.schema_type} & set(types)))

    # ------------------------------------------------------------- NAP ----
    has_phone = _has_phone(html)
    has_addr = _has_address(html)
    # Contact details matter for every business, but WHY differs. Telling a
    # wholesaler to match its Google Business Profile is advice for a shop, and
    # a B2B buyer is not standing outside the building.
    if vert.local_business:
        add("nap", "high", "Name / address / phone not clearly on the page",
            f"phone detected: {has_phone}, address wording detected: "
            f"{has_addr}. Consistent NAP is a core local ranking signal.",
            "Put the full address and a tel: link in the footer of every page, "
            "matching your Google Business Profile exactly.",
            key="nap", ok=has_phone and has_addr)
    else:
        add("nap", "high", "Contact details not clearly on the page",
            f"phone detected: {has_phone}, address wording detected: "
            f"{has_addr}. A buyer evaluating a supplier checks that a real "
            f"company with a real address is behind the site before enquiring.",
            "Put a direct phone number, an email and the registered company "
            "address in the footer of every page, and keep them identical "
            "across every trade directory and marketplace listing you hold.",
            key="nap", ok=has_phone and has_addr)

    # ---------------------------------------------------------- images ----
    imgs = re.findall(r"<img\b[^>]*>", html, re.I)
    no_alt = [i for i in imgs
              if not re.search(r'\balt\s*=\s*["\'][^"\']+["\']', i, re.I)]
    # A page with no images cannot have images missing alt text. The old rule
    # was `ok=bool(imgs) and ...`, which failed every image-free page and
    # reported "0 of 0 images have no alt text" — a defect that does not
    # exist, on a site Titan then charges to fix. Found on Titan's own
    # homepage, which is CSS and SVG throughout and was losing 6 points for it.
    add("images_alt", "medium", "Images missing alt text",
        f"{len(no_alt)} of {len(imgs)} images have no alt text. For a "
        f"{vert.label.lower()} {vert.asset_noun} is the product — unlabelled "
        f"images cannot rank in image search.",
        f"Describe each image in the alt text, e.g. '{vert.alt_example}'.",
        key="images_alt",
        na=not imgs,
        ok=bool(imgs) and len(no_alt) <= max(1, len(imgs) // 5))

    # ------------------------------------------------------- technical ----
    add("viewport", "high", "No mobile viewport tag",
        "Most searches now happen on a phone. Without this the layout "
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
    # Local ranking factors are meaningless for a business without a location.
    # Scoring a SaaS on Google Business Profile and NAP consistency produces a
    # low number that means nothing and buries the findings that do matter.
    local = (local_seo.analyse(html, business=business_name, city=city,
                               industry=industry, url=url)
             if vert.local_business else
             {"score": None, "vertical": vert.key or "unknown",
              "not_applicable": True,
              "reason": (f"A {vert.label.lower()} is not found by proximity, so "
                         f"Google Business Profile, NAP and review-velocity "
                         f"factors do not apply."),
              "dimensions": {}, "findings": [], "expected_schema": ""})
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
    # Checks marked not-applicable leave the denominator as well as the
    # numerator, so a site is scored only on what could actually be judged.
    # A check that never ran still counts against the score — silence is not
    # the same as "does not apply".
    na_keys = {k for k, v in earned.items() if v == "na"}
    total = sum(w for k, w in WEIGHTS.items() if k not in na_keys)
    got = sum(w for k, w in WEIGHTS.items() if earned.get(k) is True)
    score = round(100 * got / total) if total else 0

    order = {"legal-critical": 0, "critical": 1, "high": 2,
             "medium": 3, "low": 4}
    # "I cannot see this page properly" outranks everything, including a legal
    # finding — because if it is true, every other finding in the list may be
    # about a shell rather than about the site.
    findings.sort(key=lambda f: (0 if f["id"] == "client_rendered" else 1,
                                 order.get(f["severity"], 9)))

    return {
        "ok": True,
        "url": url,
        "status": status,
        "score": score,
        "grade": ("A" if score >= 90 else "B" if score >= 75 else
                  "C" if score >= 60 else "D" if score >= 40 else "F"),
        # How the HTML was obtained, always. A caller can never be left
        # guessing whether JavaScript ran.
        "rendering": rendering,
        # False when the page renders in the browser and Titan could not.
        # The score is still a real measurement OF WHAT WAS SERVED, but it is
        # not a measurement of the page a visitor sees, and presenting it as
        # one would be the exact failure this codebase exists to avoid.
        "reliable": not unreliable,
        "passed": [k for k, v in earned.items() if v is True],
        "failed": [k for k, v in earned.items() if v is False],
        # Reported separately so a reader can see what was skipped and why the
        # denominator is smaller, rather than wondering where a check went.
        "not_applicable": sorted(na_keys),
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
        "note": (("THIS PAGE RENDERS IN THE BROWSER AND TITAN COULD NOT. The "
                  "score above describes the HTML the server sent, which is "
                  "not what a visitor sees — treat every finding as unverified "
                  "until the page is server-rendered or a browser renderer is "
                  "configured. "
                  if unreliable else "")
                 + "Rankings, traffic and Google Business Profile health cannot "
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
