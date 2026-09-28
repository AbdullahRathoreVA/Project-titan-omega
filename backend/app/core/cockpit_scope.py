"""What a subscriber may call through /api/me, and who is calling.

ALLOWED below is the only place a route becomes reachable with a
subscriber's token. Anything not listed returns 404, so a new route stays
closed to subscribers until it is added here together with a test in
tests/test_cockpit.py showing it only reads that subscriber's data.

A route is safe to add when everything it returns comes from STORE (bound to
the subscriber's workspace for the request) or from data filtered to that
subscriber. A route that reads a global source - site traffic, the billing
table, environment credentials - isn't, however harmless it looks.
"""

from __future__ import annotations

import contextvars
import re
from typing import Tuple

# (method, path) on the inner /api path, full match. Read-only views built
# from the Store alone.
ALLOWED: Tuple[Tuple[str, str], ...] = (
    ("GET", r"/api/status"),
    ("GET", r"/api/divisions"),
    ("GET", r"/api/agents"),
    ("GET", r"/api/opportunities"),
    ("GET", r"/api/feed"),
    ("GET", r"/api/deliverables"),
    ("GET", r"/api/executions"),
    ("GET", r"/api/decisions"),
    ("GET", r"/api/posts"),
    ("GET", r"/api/progress"),
    ("GET", r"/api/performance"),
    ("GET", r"/api/finance"),
    ("GET", r"/api/leads"),
    ("GET", r"/api/revenue/entries"),
    # CRM. The handlers use the shared owner-tagged table through
    # finance._owner(), which is the subscriber here.
    ("POST", r"/api/leads"),
    ("POST", r"/api/leads/[^/]+/status"),
    ("DELETE", r"/api/leads/[^/]+"),
    ("POST", r"/api/leads/discover"),
    ("POST", r"/api/leads/[^/]+/research"),
    # Clients and SEO. api/mine.py only serves the subscriber's own businesses
    # and answers anything else with the same 404 as a missing one.
    ("GET", r"/api/mine/clients"),
    ("POST", r"/api/mine/clients"),
    ("GET", r"/api/mine/clients/[^/]+"),
    ("DELETE", r"/api/mine/clients/[^/]+"),
    ("POST", r"/api/mine/clients/[^/]+/seo"),
    ("GET", r"/api/mine/clients/[^/]+/seo/schema"),
    ("GET", r"/api/mine/clients/[^/]+/report\.pdf"),
    ("POST", r"/api/mine/clients/[^/]+/watch"),
    ("GET", r"/api/mine/watch"),
    ("GET", r"/api/mine/discovery"),
    # Voice. api/voice.py makes the subscriber the session owner, so they only
    # see and act on their own sessions.
    ("GET", r"/api/voice/live"),
    ("GET", r"/api/voice/capabilities"),
    ("GET", r"/api/voice/sessions"),
    ("GET", r"/api/voice/sessions/[^/]+"),
    ("POST", r"/api/voice/sessions"),
    ("POST", r"/api/voice/sessions/[^/]+/(state|turn|tool|escalate|end)"),
    ("POST", r"/api/voice/sessions/[^/]+/tool/[^/]+/(approve|finish)"),
    # Ask Titan answers from the subscriber's own workspace and businesses
    # (router.assistant), metered against their plan.
    ("POST", r"/api/assistant"),
    # Finance. Expenses and sales go to the subscriber's workspace ledger.
    ("POST", r"/api/finance/expense"),
    ("DELETE", r"/api/finance/expense/[^/]+"),
    ("POST", r"/api/revenue/log"),
    ("DELETE", r"/api/revenue/entry/[^/]+"),
    # Executive: the period report reads their ledger, and engines/bi.py limits
    # its client list and lead funnel to theirs.
    ("GET", r"/api/bi/[^/]+"),
    ("GET", r"/api/mine/seo-overview"),
    # War Room. engines/owner.py points research, the debate, the SEO co-pilot
    # and the content factory at the subscriber's businesses, and api/growth.py
    # rate-limits them. /api/devops/pr stays founder-only.
    ("GET", r"/api/growth/intel"),
    ("POST", r"/api/growth/scan"),
    ("POST", r"/api/warroom/debate"),
    ("POST", r"/api/seo/report"),
    ("POST", r"/api/content/repurpose"),
    # APIs: the public-API catalogue and keyless live adapters. Public data only.
    ("GET", r"/api/apis"),
    ("GET", r"/api/apis/integrated"),
    ("GET", r"/api/apis/live/rates"),
    ("GET", r"/api/apis/live/weather"),
    # Dashboard panels. Agent chat, the command bar, the Urdu briefing and Growth
    # Studio work for the subscriber's business (engines/owner.py); lead finding
    # shares the War Room's hourly limit.
    ("POST", r"/api/agents/[^/]+/chat"),
    ("POST", r"/api/command"),
    # The command bar posts here (lib/api.ts `command`). For a subscriber it acts
    # on their business in their workspace and never posts or sends anything.
    ("POST", r"/api/agent/act"),
    ("GET", r"/api/voice-report"),
    ("POST", r"/api/intel/generate"),
    ("POST", r"/api/intel/news"),
    ("POST", r"/api/leads/find"),
    # Posts are drafted and queued in their workspace. publisher.publish never
    # uses the founder's webhook for them.
    ("GET", r"/api/next-post"),
    ("POST", r"/api/next-post/(regenerate|approve)"),
    ("POST", r"/api/posts"),
    ("POST", r"/api/posts/[^/]+/publish"),
    # Telegram: Titan's bot, linked to the subscriber's chat with a one-time code
    # (core/telegram_links.py). Job Radar uses the profile they write; its scans
    # share the hourly limit.
    ("GET", r"/api/telegram/status"),
    ("GET", r"/api/telegram/log"),
    ("POST", r"/api/telegram/link-code"),
    ("DELETE", r"/api/telegram/link"),
    ("GET", r"/api/jobs"),
    ("POST", r"/api/jobs/profile"),
    ("POST", r"/api/jobs/scan"),
    ("POST", r"/api/jobs/proposal"),
    ("POST", r"/api/jobs/[^/]+/applied"),
)

_COMPILED = tuple((m, re.compile(p + r"\Z")) for m, p in ALLOWED)

_customer: "contextvars.ContextVar[str]" = contextvars.ContextVar(
    "titan_customer", default="")


def allowed(method: str, inner_path: str) -> bool:
    method = "GET" if method == "HEAD" else method
    return any(m == method and rx.match(inner_path) for m, rx in _COMPILED)


def bind_customer(email: str) -> "contextvars.Token":
    return _customer.set(email)


def unbind_customer(token: "contextvars.Token") -> None:
    _customer.reset(token)


def is_customer() -> bool:
    """True while serving a subscriber's /api/me request. Check this before
    anything that would act with the founder's own credentials.
    """
    return bool(_customer.get())


def customer_email() -> str:
    return _customer.get()
