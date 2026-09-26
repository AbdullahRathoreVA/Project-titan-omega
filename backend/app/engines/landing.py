"""Server-rendered landing pages, built from data Titan already relies on.

Titan scores 100/100 on its own technical audit and ranks for essentially
nothing, because a perfect score on four pages is a perfect score on four
pages. Search needs something to match a query against.

The pages here are generated, but they are **not** thin. Every fact on them —
the statute, the fine range, the Abmahnung exposure, the schema type, the
ranking signals — is the same data the audit engine uses to charge clients. A
page about Impressum requirements in Germany cites §5 DDG and the real penalty
range because that is what `compliance.JURISDICTIONS['DE']` actually contains.
If the law changes, the audit and the landing page change together; they cannot
drift, because there is one source.

Two deliberate limits, both to stay on the right side of thin-content:

* **Only two page families**, one per jurisdiction and one per vertical — 25
  pages, not the 144 that 16 × 9 would produce. A restaurant-in-Austria page
  and a bakery-in-Austria page would repeat the same statute with a different
  noun, which is exactly the pattern Titan's own audit flags on client sites.
  Selling an SEO product while spamming an index would be indefensible.
* **Server-rendered HTML**, like /pricing. The dashboard is a client-rendered
  SPA, so a crawler sees an empty shell — Titan's own audit caught that on the
  homepage. These pages must be readable with JavaScript disabled.
"""

from __future__ import annotations

import html as _html
from typing import Optional

from . import compliance, verticals

SITE = "https://titanomega-ai.com"

_CSS = """
:root{--void:#05070d;--panel:#0a0e1a;--edge:#16203a;--cyan:#22d3ee;
      --emerald:#34d399;--amber:#fbbf24;--rose:#fb7185;--mut:#64748b;--ink:#e2e8f0}
*{box-sizing:border-box}
body{margin:0;background:var(--void);color:var(--ink);
     font:16px/1.65 ui-sans-serif,system-ui,-apple-system,Segoe UI,sans-serif}
.wrap{max-width:760px;margin:0 auto;padding:44px 20px 72px}
a{color:var(--cyan)}
.mark{font-size:12px;letter-spacing:.3em;color:var(--cyan);margin-bottom:14px}
h1{font-size:clamp(26px,4.6vw,36px);margin:0 0 12px;font-weight:600;
   letter-spacing:-.02em;text-wrap:balance}
h2{font-size:19px;margin:34px 0 10px;font-weight:600}
.lede{color:#cbd5e1;font-size:17px;margin:0 0 8px}
.sub{color:var(--mut);font-size:14px;margin:0 0 26px}
.card{background:var(--panel);border:1px solid var(--edge);border-radius:12px;
      padding:18px 20px;margin:14px 0}
.k{font-size:11px;letter-spacing:.16em;text-transform:uppercase;color:var(--mut)}
.v{font-size:15px;margin-top:4px}
.warn{border-color:rgba(251,113,133,.35);background:rgba(251,113,133,.06)}
.warn .v{color:var(--rose)}
ul{padding-left:20px;margin:10px 0}
li{margin:5px 0;color:#cbd5e1;font-size:15px}
code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:13.5px;
     background:rgba(255,255,255,.06);padding:1px 6px;border-radius:4px}
.cta{display:inline-block;margin-top:8px;padding:12px 22px;border-radius:10px;
     border:1px solid rgba(52,211,153,.45);background:rgba(52,211,153,.12);
     color:var(--emerald);text-decoration:none;font-weight:600}
.foot{margin-top:40px;padding-top:18px;border-top:1px solid var(--edge);
      font-size:13px;color:var(--mut)}
.tags{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px}
.tag{font-family:ui-monospace,monospace;font-size:11.5px;color:var(--mut);
     border:1px solid var(--edge);border-radius:999px;padding:2px 9px}
"""


def _e(s) -> str:
    return _html.escape(str(s or ""))


# The audit's own limit. A title outside this range is a finding Titan raises
# against paying clients, so shipping one on its own pages is indefensible —
# and it is exactly what /compliance/{code} did at 70 characters.
TITLE_MAX = 65
TITLE_MIN = 15


def _fit_title(base: str, suffixes: tuple[str, ...]) -> str:
    """The longest suffix that still fits inside the audit's own limit.

    Truncating mid-word would produce a title Titan would flag, so the
    alternatives are written out and the best one that fits is used.

    **Measured on the ESCAPED string**, because that is what the audit reads.
    An "&" is one character here and five (`&amp;`) in the HTML the crawler
    parses, which is how "…Switzerland — Impressum & GDPR rules" measured 64
    in Python and 68 to Titan's own engine. Written suffixes therefore avoid
    ampersands, and the check no longer trusts the unescaped length.
    """
    for suffix in suffixes:
        if len(_e(base + suffix)) <= TITLE_MAX:
            return base + suffix
    return base[:TITLE_MAX].rstrip(" -—·,")


def _schema_graph(title: str, desc: str, canonical: str,
                  breadcrumb: list[tuple[str, str]]) -> str:
    """JSON-LD for a landing page. One source of truth with the product schema.

    Titan's audit tells clients that only ~17% of sites publish schema and that
    it is how AI answer engines decide what to quote. These 25 pages published
    none and scored 60-70/C against Titan's own engine — the single loudest
    "physician, heal thyself" left in the product.

    The SoftwareApplication and Organization nodes come from
    `self_seo.structured_data()` rather than being written again here, so the
    marked-up price can never drift from the price actually charged. The
    `Article` node describes this page.

    **No datePublished or dateModified.** Google's Article guidance asks for
    them and every SEO checklist says to add them, but these pages are rendered
    from live data and nothing records when their content last changed. A
    plausible date would be a fabricated fact published as structured data,
    which is the one thing this codebase does not do. Omitted rather than
    invented.

    **No aggregateRating.** There are no reviews.
    """
    import json

    graph: list[dict] = []
    try:
        from . import self_seo
        product = self_seo.structured_data()
        graph.extend(n for n in product.get("@graph", [])
                     if isinstance(n, dict))
    except Exception:
        # A landing page must still render if the plan table is unavailable.
        # Fewer nodes is a smaller claim, not a false one.
        pass

    graph.append({
        "@type": "Article",
        "headline": title,
        "description": desc,
        "url": canonical,
        "mainEntityOfPage": {"@type": "WebPage", "@id": canonical},
        "inLanguage": "en",
        "isAccessibleForFree": True,
        "author": {"@type": "Organization", "name": "Titan Omega",
                   "url": SITE},
        "publisher": {"@type": "Organization", "name": "Titan Omega",
                      "url": SITE, "logo": f"{SITE}/icons/icon-512.png"},
    })
    graph.append({
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": i, "name": name, "item": url}
            for i, (name, url) in enumerate(breadcrumb, start=1)
        ],
    })
    blob = json.dumps({"@context": "https://schema.org", "@graph": graph},
                      ensure_ascii=False, indent=1)
    # The page is server-rendered and every value is either escaped text or a
    # value Titan generated, but "</script" inside a JSON string would still
    # end the block early. Escaping the slash is the standard defence and stays
    # valid JSON.
    return ('<script type="application/ld+json">'
            + blob.replace("</", "<\\/") + "</script>")


def _contact_block() -> str:
    """Titan's own phone and postal address, when it has any to publish.

    This is the last failing check on all 25 of these pages and the only thing
    holding them at 89/B. It is empty until `TITAN_PHONE` and the four address
    variables are set — see `core/contact.py` for why a partial address is
    published as nothing rather than as something."""
    from ..core import contact
    return contact.html_block()


def _page(title: str, desc: str, canonical: str, body: str,
          breadcrumb: Optional[list[tuple[str, str]]] = None) -> str:
    schema = _schema_graph(title, desc, canonical,
                           breadcrumb or [("Titan Omega", SITE)])
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_e(title)}</title>
<meta name="description" content="{_e(desc)}">
<link rel="canonical" href="{_e(canonical)}">
<link rel="icon" href="/favicon.png">
<meta name="theme-color" content="#05070d">
<meta property="og:title" content="{_e(title)}">
<meta property="og:description" content="{_e(desc)}">
<meta property="og:url" content="{_e(canonical)}">
<meta property="og:type" content="article">
{schema}
<style>{_CSS}</style>
</head>
<body><div class="wrap">
<div class="mark"><a href="/" style="text-decoration:none;color:inherit">TITAN OMEGA</a></div>
{body}
<div class="foot">
  <a href="/join">Run a free audit</a> · <a href="/pricing">Pricing</a> ·
  <a href="/privacy">Privacy</a> · <a href="/terms">Terms</a>
  {_contact_block()}
  <p>Every figure above comes from the same rule set Titan applies when it
  audits a real site. Legal information, not legal advice — confirm anything
  consequential with a qualified lawyer in that jurisdiction.</p>
</div>
</div></body></html>"""


# ------------------------------------------------------------ compliance --
def compliance_slugs() -> list[str]:
    return sorted(k.lower() for k in compliance.JURISDICTIONS)


def compliance_page(code: str) -> str | None:
    j = compliance.JURISDICTIONS.get((code or "").upper())
    if not j:
        return None
    name = j["name"]
    canonical = f"{SITE}/compliance/{code.lower()}"
    # Was "…— what regulators actually require": 70 characters for Germany,
    # which Titan's own audit fails as a critical finding. Measured at 60/C on
    # the live page before this.
    title = _fit_title(f"Website legal compliance in {name}", (
        " — Impressum, GDPR and cookie rules",
        " — Impressum and GDPR rules",
        " — what regulators require",
        " — the legal rules",
        " — the rules"))
    desc = (f"The imprint, privacy and cookie-consent rules that apply to a "
            f"business website in {name}, with the statute and the penalty "
            f"range. Checked automatically by Titan Omega.")

    imprint = ("required" if j.get("imprint_required") else "not mandated")
    rows = [
        ("Governing rule", j.get("law", "—")),
        ("Imprint / provider identification", imprint),
        ("Cookie consent before non-essential cookies",
         "required" if j.get("cookie_consent") else "not required"),
        ("Site language checked", j.get("language", "—")),
    ]
    body = [f"<h1>{_e(title)}</h1>",
            f'<p class="lede">{_e(desc)}</p>',
            '<p class="sub">Titan checks every item on this page automatically '
            'and reports each one separately — legal findings are never '
            'averaged into an SEO score, because a missing imprint is not '
            '"partly fixed" by a good page title.</p>']

    for k, v in rows:
        body.append(f'<div class="card"><div class="k">{_e(k)}</div>'
                    f'<div class="v">{_e(v)}</div></div>')

    if j.get("imprint_fine"):
        body.append('<div class="card warn"><div class="k">Penalty range</div>'
                    f'<div class="v">{_e(j["imprint_fine"])}</div></div>')
    if j.get("abmahnung_risk"):
        body.append('<div class="card warn"><div class="k">Competitor warning '
                    'letters (Abmahnung)</div><div class="v">Yes — in '
                    f'{_e(name)} a competitor or a consumer association can '
                    'send a formal warning letter and invoice you for their '
                    'legal costs. This is the expensive part, and it does not '
                    'require a regulator to act.</div></div>')

    for label, key in (("Imprint page must be findable as", "imprint_terms"),
                       ("Privacy policy must be findable as", "privacy_terms"),
                       ("Terms page must be findable as", "terms_terms")):
        terms = j.get(key) or []
        if terms:
            tags = "".join(f'<span class="tag">{_e(t)}</span>' for t in terms)
            body.append(f"<h2>{_e(label)}</h2><div class=\"tags\">{tags}</div>")

    body.append("<h2>How Titan checks this</h2><ul>"
                "<li>Fetches the site and looks for a link matching the terms "
                "above, in the local language — not just the English word.</li>"
                "<li>Reports each requirement separately, with the statute, so "
                "a finding can be handed to a lawyer or a developer as-is.</li>"
                "<li>Re-checks on a schedule, so a page removed during a "
                "redesign is caught rather than discovered by a warning "
                "letter.</li></ul>")
    body.append('<p><a class="cta" href="/join">Check a site free — no card</a></p>')

    others = [c for c in compliance_slugs() if c != code.lower()]
    links = " · ".join(
        f'<a href="/compliance/{c}">{_e(compliance.JURISDICTIONS[c.upper()]["name"])}</a>'
        for c in others)
    body.append(f"<h2>Other jurisdictions Titan checks</h2><p>{links}</p>")
    return _page(title, desc, canonical, "\n".join(body),
                 breadcrumb=[("Titan Omega", SITE),
                             ("Compliance", f"{SITE}/compliance/{code.lower()}"),
                             (name, canonical)])


# -------------------------------------------------------------- verticals --
def vertical_slugs() -> list[str]:
    return sorted(verticals.VERTICALS)


def vertical_page(key: str) -> str | None:
    v = verticals.VERTICALS.get((key or "").lower())
    if not v:
        return None
    label = v.label
    canonical = f"{SITE}/seo/{key.lower()}"
    title = _fit_title(f"SEO for a {label.lower()}", (
        " — what actually moves the ranking",
        " — what moves the ranking",
        " — the ranking factors"))
    local = getattr(v, "local_business", False)
    desc = (f"The structured data, ranking signals and content checks that "
            f"matter for a {label.lower()}, and the ones that do not. Audited "
            f"automatically by Titan Omega.")

    body = [f"<h1>{_e(title)}</h1>",
            f'<p class="lede">{_e(desc)}</p>',
            '<p class="sub">Titan scores technical, local and legal findings '
            'separately. Averaging them hides the one that costs money.</p>']

    body.append('<div class="card"><div class="k">Schema.org type</div>'
                f'<div class="v"><code>{_e(v.schema_type)}</code></div></div>')
    if getattr(v, "extra_schema", ""):
        body.append('<div class="card"><div class="k">Additional markup that '
                    'earns rich results</div>'
                    f'<div class="v">{_e(v.extra_schema)}</div></div>')

    if local:
        body.append('<div class="card"><div class="k">Local ranking</div>'
                    '<div class="v">Applies. Proximity, a consistent name / '
                    'address / phone across the web, and a complete business '
                    'profile carry real weight here.</div></div>')
    else:
        body.append('<div class="card"><div class="k">Local ranking</div>'
                    f'<div class="v">Does <strong>not</strong> apply. A buyer '
                    f'finds a {_e(label.lower())} by searching the product or '
                    'the specification, never by proximity — so map-pack '
                    'tactics are wasted effort. Titan scores this vertical as '
                    'B2B and reports local signals as not applicable rather '
                    'than as failures.</div></div>')

    signals = verticals.VERTICAL_SIGNALS.get(key.lower(), [])
    if signals:
        tags = "".join(f'<span class="tag">{_e(s)}</span>' for s in signals)
        body.append("<h2>Terms that identify this vertical</h2>"
                    "<p class=\"sub\">Titan detects the vertical from the page "
                    "itself rather than asking, so an audit applies the right "
                    "rules even when nobody filled in a form.</p>"
                    f'<div class="tags">{tags}</div>')

    if getattr(v, "asset_noun", ""):
        body.append("<h2>Images</h2>"
                    f'<p>For a {_e(label.lower())}, {_e(v.asset_noun)} is the '
                    'product. Unlabelled images cannot rank in image search. '
                    'A usable alt text reads like: '
                    f'<code>{_e(getattr(v, "alt_example", ""))}</code></p>')

    body.append('<p><a class="cta" href="/join">Audit a site free — no card</a></p>')

    others = [s for s in vertical_slugs() if s != key.lower()]
    links = " · ".join(
        f'<a href="/seo/{s}">{_e(verticals.VERTICALS[s].label)}</a>'
        for s in others)
    body.append(f"<h2>Other business types Titan audits</h2><p>{links}</p>")
    return _page(title, desc, canonical, "\n".join(body),
                 breadcrumb=[("Titan Omega", SITE),
                             ("SEO by business type", f"{SITE}/seo/{key.lower()}"),
                             (label, canonical)])


def all_paths() -> list[tuple[str, float, str]]:
    """(path, priority, changefreq) for the sitemap."""
    out = [(f"/compliance/{c}", 0.7, "monthly") for c in compliance_slugs()]
    out += [(f"/seo/{s}", 0.7, "monthly") for s in vertical_slugs()]
    return out
