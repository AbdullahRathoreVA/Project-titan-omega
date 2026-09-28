"""Research one lead, then draft outreach based on what was found.

`/api/leads/find` finds prospects and the agent layer can draft sales copy,
but neither knows anything about the specific business, so the result reads
like every other cold email. This runs Titan's own audit against the lead's
website and writes the outreach from the findings: "your site has no
Impressum, which §5 DDG requires in Germany, and three pages are missing meta
descriptions" is specific and checkable.

Rules:

1. Never invent a finding. If the lead has no website or it can't be
   reached, the draft says so and makes no audit-based claims. Citing a
   problem the recipient doesn't have loses the deal on the first reply.
2. Never send. This returns a draft; nothing reaches a real person without
   the founder's approval, since a spam complaint or platform ban can end
   the service a client pays for. A test checks this module can't send.
3. Works without an API key. With no LLM configured the draft is composed
   from the real findings; a key only improves the wording.
"""

from __future__ import annotations

import re
from typing import Optional

from ..core import llm, model_router
from . import client_seo

# Severity order for picking what to lead with. Legal comes first: it's the
# clearest finding Titan produces and the hardest for an owner to dismiss as
# "SEO opinion".
_SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}

_URL_RE = re.compile(r"https?://[^\s,;<>\"')]+|(?:www\.)[^\s,;<>\"')]+", re.I)
_DOMAIN_RE = re.compile(
    r"\b([a-z0-9][a-z0-9-]{0,61}\.(?:com|net|org|de|pk|co|io|ai|shop|store|"
    r"eu|uk|fr|es|it|nl|at|ch|info|biz))\b", re.I)


def find_website(lead: dict) -> str:
    """Pull a URL out of whatever the lead record carries.

    Leads come from search results, manual entry and imports, so the address
    may be in the note rather than a tidy field. "" means there's nothing to
    audit - don't guess.
    """
    blob = " ".join(str(lead.get(k, "") or "") for k in
                    ("website", "contact", "note", "name", "source"))
    m = _URL_RE.search(blob)
    if m:
        url = m.group(0).rstrip(".,)")
        return url if url.lower().startswith("http") else "https://" + url
    m2 = _DOMAIN_RE.search(blob)
    if m2:
        return "https://" + m2.group(1)
    return ""


def _top_findings(audit: dict, limit: int = 3) -> list[dict]:
    findings = list(audit.get("findings", []) or [])
    findings.sort(key=lambda f: (
        # Legal findings first within their severity band.
        _SEVERITY_RANK.get(str(f.get("severity", "info")).lower(), 4),
        0 if "legal" in str(f.get("category", "")).lower() else 1,
    ))
    return findings[:limit]


def research(lead: dict) -> dict:
    """Audit the lead's own website. Never guesses."""
    website = find_website(lead)
    if not website:
        return {
            "ok": False,
            "website": "",
            "reason": ("No website found on this lead. Add one to the lead's "
                       "contact or note field — without a site there is "
                       "nothing to audit and nothing specific to say."),
            "findings": [],
        }

    audit = client_seo.audit(website, business_name=lead.get("name", ""),
                            city="", country="", industry="")
    if not audit.get("ok"):
        return {
            "ok": False,
            "website": website,
            "reason": (f"Titan could not reach {website}: "
                       f"{audit.get('error', 'unknown error')}. No claims are "
                       f"being made about a site that was not read."),
            "findings": [],
        }

    top = _top_findings(audit)
    return {
        "ok": True,
        "website": website,
        "score": audit.get("score"),
        "grade": audit.get("grade"),
        "total_findings": len(audit.get("findings", []) or []),
        "findings": [
            {"id": f.get("id", ""), "severity": f.get("severity", "info"),
             "title": f.get("title", ""), "detail": str(f.get("detail", ""))[:240]}
            for f in top
        ],
        "note": ("Every claim below came from crawling the site just now. "
                 "Nothing here is generic."),
    }


def _fallback_draft(lead: dict, res: dict, lang: str) -> str:
    """A usable message with no LLM key, composed from real findings."""
    name = lead.get("name", "there")
    bullets = "\n".join(f"  • {f['title']}" for f in res["findings"])
    plural = "issues" if len(res["findings"]) != 1 else "issue"
    more = ""
    if res.get("total_findings", 0) > len(res["findings"]):
        more = (f"\n\nThere were {res['total_findings']} in total — these are "
                f"the {len(res['findings'])} worth fixing first.")
    # The legal line is only true when a legal finding is present; printing it
    # next to purely technical findings would invent a claim.
    legal = any("legal" in str(f.get("id", "")).lower()
                or "impressum" in str(f.get("id", "")).lower()
                or "privacy" in str(f.get("id", "")).lower()
                or "cookie" in str(f.get("id", "")).lower()
                or "legal" in str(f.get("title", "")).lower()
                for f in res["findings"])
    closer = (
        "The legal one matters most — that is the kind a regulator or a "
        "competitor can act on, and it is usually a same-day fix.\n\n"
        if legal else
        "Each of these is a change to the page itself, not a monthly retainer "
        "— they are the sort of thing that moves a ranking within weeks.\n\n"
    )
    return (
        f"Hi {name},\n\n"
        f"I ran a technical and legal check on {res['website']} this morning. "
        f"It scored {res['score']}/100. The {plural} that stood out:\n\n"
        f"{bullets}{more}\n\n"
        f"{closer}"
        f"Happy to send the full report, no charge. Worth a look?\n\n"
        f"— Abdullah"
    )


def draft(lead: dict, res: dict, lang: str = "en") -> dict:
    """Write the outreach. Never sends it."""
    if not res.get("ok"):
        return {
            "ready": False,
            "reason": res.get("reason", "Nothing was researched."),
            "message": "",
            "sent": False,
        }

    facts = "\n".join(
        f"- [{f['severity']}] {f['title']}: {f['detail']}"
        for f in res["findings"])

    body = llm.complete(
        task=model_router.OUTREACH_DRAFT,
        system=("You write short, specific B2B outreach for Abdullah, who sells "
                "SEO and legal-compliance audits. Rules you must follow: use "
                "ONLY the findings given — never add a problem that is not "
                "listed; no flattery, no 'I hope this finds you well', no "
                "invented statistics; under 130 words; end with one simple "
                "question. Plain text, no markdown."),
        prompt=(f"Business: {lead.get('name', 'the business')}\n"
                f"Website: {res['website']}\n"
                f"Audit score: {res['score']}/100 (grade {res['grade']})\n"
                f"Findings found by crawling their site just now:\n{facts}\n\n"
                f"Write the outreach message in {lang}."),
        max_tokens=400,
    )

    message = (body or "").strip() or _fallback_draft(lead, res, lang)
    return {
        "ready": True,
        "message": message,
        "generated_by": "llm" if body else "template",
        "grounded_in": [f["id"] for f in res["findings"]],
        # In the payload, not just the docstring: the UI shows it, and a person must
        # approve before anything reaches a real recipient.
        "sent": False,
        "note": ("Draft only — Titan has not contacted anyone. Review it, then "
                 "send it yourself from your own mailbox. Automated sending "
                 "from a shared IP is how a domain gets blocked."),
    }
