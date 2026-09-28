"""Which business the growth engines are working for on this request.

The War Room, SEO co-pilot and content factory run for the founder by
default. From a subscriber's cockpit (/api/me) they must work on that
subscriber's businesses only; these helpers tell each engine which case
it is in.
"""

from __future__ import annotations

from typing import Optional


def subscriber_businesses() -> Optional[list]:
    """The subscriber's businesses, or None for the founder and the heartbeat.

    An empty list means a subscriber who hasn't added a business yet.
    """
    from ..core import cockpit_scope
    email = cockpit_scope.customer_email()
    if not email:
        return None
    from ..core import billing, clients
    rows = [clients.public(cid) for cid in billing.owned_clients(email)]
    return [r for r in rows if r]


def describe(businesses: list) -> str:
    """"Name (industry, city, country, site)" for each business, for prompts."""
    parts = []
    for b in businesses[:5]:
        detail = ", ".join(x for x in (b.get("industry"), b.get("city"),
                                       b.get("country"), b.get("website")) if x)
        name = b.get("business_name") or "a business"
        parts.append(f"{name} ({detail})" if detail else name)
    return "; ".join(parts)
