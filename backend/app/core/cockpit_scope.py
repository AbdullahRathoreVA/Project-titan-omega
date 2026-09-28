"""What a subscriber may call through /api/me, and who is calling.

The allowlist below is the ONLY place a cockpit route becomes reachable with a
customer's token. Anything not listed answers 404, so a new founder route is
unreachable by customers until somebody decides it is safe and adds it here -
together with a test in tests/test_cockpit.py proving it reads only the
customer's workspace.

A route is safe to list when everything it returns comes from STORE (which is
bound to the customer's workspace for the request) or from data filtered to
that customer. A route that reads a global source - site traffic, the billing
table, environment credentials - is not, however harmless it looks.
"""

from __future__ import annotations

import contextvars
import re
from typing import Tuple

# (method, path) on the inner /api path, full match. Phase 1: read-only views
# that are built from the Store alone.
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
    # Phase 3 - CRM. The handlers read the shared owner-tagged table through
    # finance._owner(), which is the session's subscriber here.
    ("POST", r"/api/leads"),
    ("POST", r"/api/leads/[^/]+/status"),
    ("DELETE", r"/api/leads/[^/]+"),
    ("POST", r"/api/leads/discover"),
    ("POST", r"/api/leads/[^/]+/research"),
    # Phase 3 - Clients and SEO. api/mine.py serves only the subscriber's own
    # businesses and refuses anybody else's with the same 404 as a missing one.
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
    # Voice. api/voice.py passes the subscriber down as the session owner, so
    # they list, replay and act on their own sessions only.
    ("GET", r"/api/voice/live"),
    ("GET", r"/api/voice/capabilities"),
    ("GET", r"/api/voice/sessions"),
    ("GET", r"/api/voice/sessions/[^/]+"),
    ("POST", r"/api/voice/sessions"),
    ("POST", r"/api/voice/sessions/[^/]+/(state|turn|tool|escalate|end)"),
    ("POST", r"/api/voice/sessions/[^/]+/tool/[^/]+/(approve|finish)"),
    # Ask Titan answers from the subscriber's own workspace and businesses
    # (router.assistant), and the call is metered against their plan.
    ("POST", r"/api/assistant"),
    # Phase 4 - Finance. Expenses and sales are written to the subscriber's
    # own workspace ledger, which STORE is bound to for the request.
    ("POST", r"/api/finance/expense"),
    ("DELETE", r"/api/finance/expense/[^/]+"),
    ("POST", r"/api/revenue/log"),
    ("DELETE", r"/api/revenue/entry/[^/]+"),
    # Executive: the period report reads their ledger, and engines/bi.py
    # limits its client list and lead funnel to theirs.
    ("GET", r"/api/bi/[^/]+"),
    ("GET", r"/api/mine/seo-overview"),
    # Phase 5 - War Room. engines/owner.py points research, the debate, the
    # SEO co-pilot and the content factory at the subscriber's own businesses,
    # and api/growth.py rate-limits them. Opening a PR on Titan's own repo
    # (/api/devops/pr) stays founder-only.
    ("GET", r"/api/growth/intel"),
    ("POST", r"/api/growth/scan"),
    ("POST", r"/api/warroom/debate"),
    ("POST", r"/api/seo/report"),
    ("POST", r"/api/content/repurpose"),
    # APIs: the public-API catalogue and the keyless live adapters. Metadata
    # and public data only - no account, no founder credential.
    ("GET", r"/api/apis"),
    ("GET", r"/api/apis/integrated"),
    ("GET", r"/api/apis/live/rates"),
    ("GET", r"/api/apis/live/weather"),
    # Phase 6 - the rest of the dashboard. Agent chat, the command bar, the
    # Urdu briefing and Growth Studio speak for the subscriber's own business
    # (engines/owner.py); lead finding shares the War Room's hourly limit.
    ("POST", r"/api/agents/[^/]+/chat"),
    ("POST", r"/api/command"),
    ("GET", r"/api/voice-report"),
    ("POST", r"/api/intel/generate"),
    ("POST", r"/api/intel/news"),
    ("POST", r"/api/leads/find"),
    # Posts are drafted and queued in their own workspace. publisher.publish
    # never uses the founder's webhook for them - it posts to HIS accounts.
    ("GET", r"/api/next-post"),
    ("POST", r"/api/next-post/(regenerate|approve)"),
    ("POST", r"/api/posts"),
    ("POST", r"/api/posts/[^/]+/publish"),
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
    """True while serving a subscriber's /api/me request. Anything that would
    act with the founder's own credentials must check this first."""
    return bool(_customer.get())


def customer_email() -> str:
    return _customer.get()
