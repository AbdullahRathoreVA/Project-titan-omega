"""Who the growth engines are working for on this request.

The War Room, the SEO co-pilot and the content factory were written for the
founder: their prompts name his businesses. A subscriber reaches the same
engines from their own cockpit (/api/me), and there they must work on the
subscriber's businesses and nothing else. These two helpers are how each
engine finds out which case it is in.
"""

from __future__ import annotations

from typing import Optional


def subscriber_businesses() -> Optional[list]:
    """The caller's own businesses when a subscriber is asking, or None for
    the founder and the heartbeat. An empty list means a subscriber who has
    not added a business yet - not the founder."""
    from ..core import cockpit_scope
    email = cockpit_scope.customer_email()
    if not email:
        return None
    from ..core import billing, clients
    rows = [clients.public(cid) for cid in billing.owned_clients(email)]
    return [r for r in rows if r]


def describe(businesses: list) -> str:
    """"Name (industry, city, country, site)" for each business, for a prompt."""
    parts = []
    for b in businesses[:5]:
        detail = ", ".join(x for x in (b.get("industry"), b.get("city"),
                                       b.get("country"), b.get("website")) if x)
        name = b.get("business_name") or "a business"
        parts.append(f"{name} ({detail})" if detail else name)
    return "; ".join(parts)
