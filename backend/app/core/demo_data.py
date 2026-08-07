"""Demo-safe payloads for the public guest session.

One Space now serves both the founder's real dashboard and a public demo. The
guest must NEVER see real business data, so every endpoint carrying private
information is intercepted and answered from here instead of the live store.

What a guest DOES see live (genuinely impressive, zero private data): the 102
agents working through their division pipelines, divisions, opportunities,
the universe, council decisions and the activity feed (revenue lines filtered).

What a guest NEVER sees: real revenue/ledger, expenses, CRM leads, Telegram
logs, job-radar applications, generated deliverables.

Every figure below is clearly marked SAMPLE — the honesty rule applies to
demos too.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Optional

from ..store import STORE, now

# Paths whose real content is private. Anything not listed passes through live.
#
# THIS LIST IS THE WHOLE GUARD, and it fails OPEN: an endpoint added later and
# not registered here silently serves the founder's real data to every visitor
# who clicks "View the live demo". That is exactly what happened — /api/bi,
# /api/routing, /api/reflection and /api/events all shipped leaking, because
# the list was written before those endpoints existed.
#
# There is a test (test_every_founder_endpoint_is_hidden_from_guests) that
# enumerates the live route table and fails when a new private-looking endpoint
# is not covered, so the next one cannot leak silently.
_SENSITIVE_PREFIXES = (
    "/api/finance",
    "/api/leads",
    "/api/revenue",
    "/api/telegram",
    "/api/jobs",
    "/api/deliverables",
    # Executive intelligence. Real revenue, real provider error messages, the
    # internal event trace and what the platform has learned about itself —
    # none of it is a demo asset.
    "/api/bi",
    "/api/reflection",
    "/api/routing",
    "/api/tools",
    "/api/events",
    "/api/plan",
    "/api/learning",
    "/api/evolution",
    "/api/decisions",
    # Client management. This one is the worst of the set: it is not Abdullah's
    # data, it is his CLIENTS' — business names, websites, contact details and
    # their audit findings. Leaking a paying client's information to a public
    # demo is a breach of their trust and, for an EU client, a GDPR problem for
    # the operator. Found by the route-table audit test, not by inspection.
    "/api/admin",
    # Founder analytics. Every row is a real subscriber's email address, their
    # plan and what they did. This is the most personal data in the system and
    # the demo has no business version of it — blocked outright, never
    # substituted.
    "/api/founder",
    # Voice sessions carry live transcripts — what a caller actually said, in
    # their own words, plus whatever number or handle they were reached on.
    # That is the most sensitive data Titan holds. No demo substitute exists
    # and none should: blocked outright.
    "/api/voice",
)

_LEAD_STATUSES = ["new", "contacted", "replied", "won", "lost"]

# One source of truth for the demo's headline numbers, so the status card, the
# live SSE stream, the revenue ledger and the finance panel can never disagree.
DEMO_MRR = 693.0
DEMO_PIPELINE = 4200.0
DEMO_TRAFFIC = 1280


def is_revenue_event(e: dict) -> bool:
    """Real order/revenue lines must never reach a public demo visitor."""
    return e.get("kind") == "revenue" or "REAL ORDER" in str(e.get("message", ""))


def _iso(days_ago: int) -> str:
    return (now() - timedelta(days=days_ago)).isoformat()


def _epoch(days_ago: int) -> float:
    """Epoch seconds. The watch/alert payloads use numeric timestamps, not ISO,
    because that is what the real client_watch.summary() returns."""
    return (now() - timedelta(days=days_ago)).timestamp()


def _sample_expenses() -> list:
    return [
        {"id": "exp-demo-1", "amount": 12.0, "category": "tools", "note": "[SAMPLE] Domain renewal", "created_at": _iso(18)},
        {"id": "exp-demo-2", "amount": 25.0, "category": "marketing", "note": "[SAMPLE] Boosted launch post", "created_at": _iso(8)},
    ]


def _sample_revenue_entries() -> list:
    return [
        {"id": "rev-demo-5", "amount": 180.0, "source": "client", "note": "[SAMPLE] n8n workflow retainer", "created_at": _iso(2)},
        {"id": "rev-demo-4", "amount": 35.0, "source": "product", "note": "[SAMPLE] Digital product sale", "created_at": _iso(6)},
        {"id": "rev-demo-3", "amount": 240.0, "source": "client", "note": "[SAMPLE] Custom dashboard deployment", "created_at": _iso(9)},
        {"id": "rev-demo-2", "amount": 89.0, "source": "fiverr", "note": "[SAMPLE] Automation pipeline gig", "created_at": _iso(14)},
        {"id": "rev-demo-1", "amount": 149.0, "source": "client", "note": "[SAMPLE] AI chatbot build", "created_at": _iso(21)},
    ]


def _sample_clients() -> dict:
    """Sample agency portfolio for the public demo.

    This is the demo's most important screen, not a placeholder. A visitor
    evaluating Titan needs to see the one thing no competitor's SEO report
    does — a German Impressum finding priced as a fine and an Abmahnung risk —
    because that is the reason to pay. Hiding the Clients and SEO tabs from the
    demo removed the sales pitch along with the private data.

    Every value is marked [SAMPLE] and none of it is a real business.
    """
    audit = {
        "ok": True,
        "url": "https://sample-restaurant.example",
        "status": 200,
        "score": 61,
        "grade": "C",
        "passed": ["title", "viewport", "https", "canonical", "robots", "nap"],
        "failed": ["schema", "local_business", "meta_description", "images_alt",
                   "og", "sitemap", "h1"],
        "schema_types": [],
        "counts": {"legal_critical": 2, "critical": 2, "high": 4, "medium": 3,
                   "low": 1},
        "legal": {
            "country": "DE",
            "country_name": "Germany",
            "law": "§5 Digitale-Dienste-Gesetz (DDG, replaced TMG in May 2024)",
            "in_eu_eea": True,
            "abmahnung_risk": True,
            "legal_critical": 2,
            "findings": [
                {"id": "imprint", "severity": "legal-critical",
                 "title": "Missing Impressum — legal requirement, not an SEO tweak",
                 "detail": "[SAMPLE] No Impressum link found. Required by §5 DDG. "
                           "Exposure: up to €50,000 (typically €500–1,500 for a "
                           "first, minor defect). In this jurisdiction any "
                           "COMPETITOR can serve an Abmahnung over this, "
                           "demanding correction plus their legal costs — "
                           "commonly €500–1,000+.",
                 "fix": "Add an Impressum page linked from every page footer, "
                        "listing the operator's full legal name, physical "
                        "address, email, phone, and where applicable VAT ID."},
                {"id": "cookie_consent", "severity": "legal-critical",
                 "title": "Tracking without a consent banner (Google Analytics)",
                 "detail": "[SAMPLE] Analytics is loading with no detectable "
                           "consent platform. Under GDPR/ePrivacy this requires "
                           "prior opt-in.",
                 "fix": "Install a consent manager and block non-essential "
                        "scripts until the visitor opts in."},
            ],
            "disclaimer": "This is an automated check of what the page serves, "
                          "not legal advice.",
        },
        "local": {
            "score": 38,
            "vertical": "restaurant",
            "dimensions": {
                "gbp": {"label": "Google Business Profile signals", "weight": 25, "earned": 12.5},
                "reviews": {"label": "Reviews and reputation", "weight": 20, "earned": 0},
                "onpage": {"label": "Local on-page SEO", "weight": 20, "earned": 12},
                "nap": {"label": "NAP consistency", "weight": 15, "earned": 10.5},
                "schema": {"label": "Local schema markup", "weight": 10, "earned": 0},
                "authority": {"label": "Local authority signals", "weight": 10, "earned": 3.3},
            },
            "findings": [],
            "ai_search": {
                "note": "ChatGPT does NOT read Google Business Profile. It "
                        "sources local answers from the Bing index, Yelp, "
                        "TripAdvisor and Reddit.",
                "why_it_matters": "45% of consumers now use AI for local "
                                  "recommendations, up from 6%, and AI referrals "
                                  "convert at 15.9% against 1.76% for Google organic.",
                "actions": [
                    "Claim and complete Bing Places (feeds ChatGPT, Copilot, Alexa)",
                    "Claim Apple Maps / Apple Business",
                    "Build presence on TripAdvisor and Yelp",
                    "Target 'best of' local lists — the #1 AI citation factor",
                ],
            },
        },
        "findings": [
            {"id": "imprint", "severity": "legal-critical",
             "title": "Missing Impressum — legal requirement, not an SEO tweak",
             "detail": "[SAMPLE] Required by §5 DDG. Exposure up to €50,000, plus "
                       "competitor Abmahnung risk.",
             "fix": "Add an Impressum linked from every page footer."},
            {"id": "cookie_consent", "severity": "legal-critical",
             "title": "Tracking without a consent banner (Google Analytics)",
             "detail": "[SAMPLE] Trackers load before consent — the most commonly "
                       "fined GDPR defect.",
             "fix": "Install a consent manager."},
            {"id": "schema", "severity": "critical",
             "title": "No structured data (schema) found",
             "detail": "[SAMPLE] Only ~17% of sites implement schema, and it is how "
                       "AI Overviews and ChatGPT Search decide what to quote.",
             "fix": "Add JSON-LD schema. For a restaurant, start with Restaurant."},
            {"id": "local_business", "severity": "critical",
             "title": "No LocalBusiness / Restaurant schema",
             "detail": "[SAMPLE] The single highest-leverage markup for a local "
                       "business.",
             "fix": "Add Restaurant schema with address, geo, openingHours and menu."},
            {"id": "local:reviews", "severity": "high",
             "title": "Review signals not visible to search engines",
             "detail": "[SAMPLE] aggregateRating absent. Reviews are ~20% of local "
                       "ranking and VELOCITY matters more than total — rankings "
                       "drop after roughly 18 days with no new review.",
             "fix": "Publish aggregateRating and run a continuous review flow."},
            {"id": "images_alt", "severity": "medium",
             "title": "Images missing alt text",
             "detail": "[SAMPLE] 14 of 16 images have no alt text. For a restaurant "
                       "the food photography is the product.",
             "fix": "Describe each dish, e.g. 'wood-fired lamb karahi'."},
        ],
        "note": "Rankings, traffic and Google Business Profile health cannot be "
                "read over HTTP — those need Search Console and GBP access, "
                "which the client must grant.",
    }
    metrics = {"seo_audits": 4, "posts_drafted": 12, "posts_approved": 9,
               "issues_found": 11, "issues_fixed": 3}
    return {
        "total": 3, "active": 3, "expired": 0,
        "expiring_soon": [{"id": "cl-demo-1",
                           "business_name": "[SAMPLE] Trattoria Bella",
                           "days_left": 9}],
        "totals": {"seo_audits": 9, "posts_drafted": 28, "posts_approved": 21,
                   "issues_found": 26, "issues_fixed": 7},
        "clients": [
            {"id": "cl-demo-1", "business_name": "[SAMPLE] Trattoria Bella",
             "industry": "Restaurant", "website": "https://sample-restaurant.example",
             "instagram": "sample_trattoria", "city": "Bochum", "country": "Germany",
             "status": "active", "trial_days_left": 9, "last_login": None,
             "metrics": metrics, "last_audit": audit},
            {"id": "cl-demo-2", "business_name": "[SAMPLE] Zahnarztpraxis Nord",
             "industry": "dentist", "website": "https://sample-dentist.example",
             "instagram": "", "city": "Hamburg", "country": "Germany",
             "status": "active", "trial_days_left": 41, "last_login": None,
             "metrics": {"seo_audits": 3, "posts_drafted": 8, "posts_approved": 6,
                         "issues_found": 9, "issues_fixed": 2}},
            {"id": "cl-demo-3", "business_name": "[SAMPLE] Kanzlei Weber",
             "industry": "legal", "website": "https://sample-law.example",
             "instagram": "", "city": "München", "country": "Germany",
             "status": "active", "trial_days_left": 55, "last_login": None,
             "metrics": {"seo_audits": 2, "posts_drafted": 8, "posts_approved": 6,
                         "issues_found": 6, "issues_fixed": 2}},
        ],
    }


def _sample_discovery() -> dict:
    """Sellable work the demo can show being found automatically."""
    return {
        "pipeline_value_eur": 2340,
        "urgent_value_eur": 1320,
        "opportunities": [
            {"id": "op-demo-1", "offer": "[SAMPLE] Impressum + consent banner fix",
             "affected": 2, "clients": ["[SAMPLE] Trattoria Bella",
                                        "[SAMPLE] Zahnarztpraxis Nord"],
             "unit_price_eur": 660, "total_eur": 1320, "effort": "2–3 hours each",
             "urgent": True,
             "pitch": "Two clients are exposed to a fine and a competitor "
                      "Abmahnung. This is the fastest paid work available.",
             "evidence": "Found on 2 of 3 audited sites"},
            {"id": "op-demo-2", "offer": "[SAMPLE] Restaurant + LocalBusiness schema",
             "affected": 3, "clients": ["[SAMPLE] Trattoria Bella"],
             "unit_price_eur": 340, "total_eur": 1020, "effort": "1–2 hours each",
             "urgent": False,
             "pitch": "None of the three publish structured data, so none can be "
                      "quoted by AI search.",
             "evidence": "Found on 3 of 3 audited sites"},
        ],
        "risks": [
            {"id": "rk-demo-1", "severity": "critical",
             "title": "[SAMPLE] Trial ends in 9 days with no conversion call booked",
             "detail": "Trattoria Bella has had 4 audits and 9 approved posts.",
             "action": "Book the conversion call this week."},
        ],
    }


def _sample_watch() -> dict:
    return {
        "watching": 3, "unwatched": 0, "interval_hours": 6,
        "recent_alerts": [
            {"client": "[SAMPLE] Trattoria Bella", "severity": "critical",
             "message": "Impressum link disappeared from the footer overnight",
             "ts": _epoch(1)},
            {"client": "[SAMPLE] Kanzlei Weber", "severity": "medium",
             "message": "Page title changed — city no longer present",
             "ts": _epoch(3)},
        ],
        "trends": [
            {"client": "[SAMPLE] Trattoria Bella", "from": 54, "to": 61,
             "delta": 7, "checks": 12},
            {"client": "[SAMPLE] Zahnarztpraxis Nord", "from": 66, "to": 64,
             "delta": -2, "checks": 9},
        ],
        "note": "Monitoring runs on the server heartbeat, with nobody logged in. "
                "The value is the DIFF: clients notice 'your imprint disappeared "
                "yesterday', not 'your score is 67'.",
    }


def _sample_leads() -> list:
    return [
        # stage_reached mirrors the real leads: it is the furthest stage the
        # lead ever got to, which is what the funnel counts. The lost sample
        # deliberately died at 'contacted' so the demo funnel shows a real leak
        # rather than a clean staircase.
        {"id": "lead-demo-1", "name": "[SAMPLE] Horizon Digital Agency", "source": "linkedin", "contact": "[SAMPLE]",
         "note": "[SAMPLE] Wants white-label AI dashboard", "status": "replied", "stage_reached": 2,
         "created_at": _iso(5), "updated_at": _iso(1)},
        {"id": "lead-demo-2", "name": "[SAMPLE] K. Marketing Studio", "source": "fiverr", "contact": "[SAMPLE]",
         "note": "[SAMPLE] Asked for automation audit", "status": "contacted", "stage_reached": 1,
         "created_at": _iso(7), "updated_at": _iso(2)},
        {"id": "lead-demo-3", "name": "[SAMPLE] SaaS founder (beta list)", "source": "referral", "contact": "[SAMPLE]",
         "note": "[SAMPLE] Interested in enterprise tier", "status": "new", "stage_reached": 0,
         "created_at": _iso(3), "updated_at": _iso(3)},
        {"id": "lead-demo-4", "name": "[SAMPLE] Local retailer", "source": "instagram", "contact": "[SAMPLE]",
         "note": "[SAMPLE] Went quiet after the quote", "status": "lost", "stage_reached": 1,
         "created_at": _iso(11), "updated_at": _iso(6)},
        {"id": "lead-demo-5", "name": "[SAMPLE] Boutique hotel", "source": "referral", "contact": "[SAMPLE]",
         "note": "[SAMPLE] Signed the retainer", "status": "won", "stage_reached": 3,
         "created_at": _iso(18), "updated_at": _iso(4)},
    ]


def _sample_jobs() -> dict:
    return {
        "items": [
            {"score": 88, "title": "[SAMPLE] Remote AI Automation Developer", "url": "https://example.com/sample-job-1",
             "why": "[SAMPLE] Matches FastAPI + n8n + LLM integration experience", "applied": False},
            {"score": 76, "title": "[SAMPLE] Python / LLM Integration Engineer", "url": "https://example.com/sample-job-2",
             "why": "[SAMPLE] Strong overlap with multi-provider LLM work", "applied": False},
        ],
        "live": True,
        "last_scan": _iso(0),
    }


def is_sensitive(path: str) -> bool:
    return path.startswith(_SENSITIVE_PREFIXES)


def guest_payload(path: str, limit: int = 50) -> Optional[Any]:
    """Demo-safe replacement for a guest GET, or None to serve the live response."""
    # --- private business data: fully substituted -------------------------
    if path == "/api/finance":
        rev, exp = DEMO_MRR, 37.0
        return {
            "revenue_total": rev, "expenses_total": exp, "profit": rev - exp,
            "revenue_30d": 455.0, "expenses_30d": 25.0,
            "forecast_monthly_revenue": 455.0, "forecast_monthly_profit": 430.0,
            "expenses": _sample_expenses(),
        }
    # The agency portfolio and the SEO view are the demo's SELLING screens.
    # They were briefly hidden from guests along with the genuinely private
    # endpoints, which removed the pitch — a visitor could no longer see the
    # German Impressum finding, which is the single reason to pay for this.
    # Substituted rather than blocked.
    if path == "/api/admin/clients":
        return _sample_clients()
    if path == "/api/admin/discovery":
        return _sample_discovery()
    if path == "/api/admin/watch":
        return _sample_watch()
    if path.startswith("/api/admin/clients/") and path.endswith("/seo/schema"):
        return {"json_ld": (
            '{\n  "@context": "https://schema.org",\n  "@type": "Restaurant",\n'
            '  "name": "[SAMPLE] Trattoria Bella",\n'
            '  "url": "https://sample-restaurant.example",\n'
            '  "priceRange": "$$",\n  "address": {\n'
            '    "@type": "PostalAddress",\n    "streetAddress": "<street address>",\n'
            '    "addressLocality": "Bochum",\n    "addressCountry": "DE"\n  },\n'
            '  "telephone": "<phone number>",\n  "servesCuisine": "<cuisine>",\n'
            '  "acceptsReservations": "True"\n}')}
    if path.startswith("/api/admin/clients/"):
        # A single client record, for the SEO view's detail fetch.
        cid = path.rsplit("/", 1)[-1]
        for c in _sample_clients()["clients"]:
            if c["id"] == cid:
                return c
        return _sample_clients()["clients"][0]

    if path == "/api/leads":
        # Built with the REAL funnel helper, not a copy of it. When the live
        # endpoint grows a field, the demo grows it too — otherwise the guest
        # view (the one prospects are shown) renders undefined for the new key.
        from ..api.finance import LEAD_STAGES, _funnel

        items = _sample_leads()
        return {
            "items": items,
            "counts": {s: sum(1 for l in items if l.get("status") == s) for s in _LEAD_STATUSES},
            "statuses": _LEAD_STATUSES,
            "stages": LEAD_STAGES,
            **_funnel(items),
        }
    if path == "/api/revenue":
        return {
            "total": DEMO_MRR,
            "by_source": {"fiverr": 89.0, "career_mind": 0.0, "kindle": 0.0, "other": 604.0},
            "fiverr_orders": 1,
        }
    if path == "/api/revenue/entries":
        return _sample_revenue_entries()
    if path == "/api/telegram/status":
        return {"configured": True, "locked": True, "handled": 12}
    if path == "/api/telegram/log":
        return []
    if path == "/api/jobs":
        return _sample_jobs()
    if path == "/api/deliverables":
        return []
    if path == "/api/progress":
        # XP is computed from real revenue/leads, so it must be sampled too —
        # otherwise the demo shows "LV 1 · 0 XP" beside $693 of sample earnings.
        return {
            "xp": 7180, "level": 9, "level_floor": 6400, "next_level_xp": 8100,
            "milestones": [
                {"label": "First real order logged", "done": True},
                {"label": "First lead contacted", "done": True},
                {"label": "First lead won", "done": True},
                {"label": "10 posts scheduled", "done": True},
                {"label": "First deliverable produced", "done": True},
                {"label": "First job application sent", "done": False},
                {"label": "$1,000 earned", "done": False},
            ],
        }

    # --- live but money-masked -------------------------------------------
    if path == "/api/status":
        from . import executive

        s = executive.empire_status(STORE)
        s["mrr"] = DEMO_MRR          # SAMPLE — never the founder's real revenue
        s["pipeline_value"] = DEMO_PIPELINE
        s["traffic"] = DEMO_TRAFFIC
        s["updated_at"] = s["updated_at"].isoformat() if hasattr(s["updated_at"], "isoformat") else s["updated_at"]
        return s

    if path == "/api/feed":
        out = []
        for e in STORE.recent_feed(limit):
            # Never leak real order/revenue lines into the public demo.
            if is_revenue_event(e):
                continue
            ev = dict(e)
            ts = ev.get("timestamp")
            ev["timestamp"] = ts.isoformat() if hasattr(ts, "isoformat") else ts
            out.append(ev)
        return out

    return None
