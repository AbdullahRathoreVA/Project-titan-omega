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
