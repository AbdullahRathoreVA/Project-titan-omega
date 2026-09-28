"""Decides whether a caller may touch a business's data.

Titan is multi-tenant: one subscriber pays for several client businesses, and
their data (audit findings, website credentials, voice transcripts, previous
page content Titan has edited) must never cross between subscribers.

The ownership check used to be repeated in every endpoint:

    email = billing.resolve(token)
    if not email or cid not in billing.owned_clients(email):
        raise HTTPException(404)

That works until a new endpoint forgets it, and nothing fails when it does.
So this module has two parts:

- `require_owner()` resolves the token, checks ownership, binds the tenant to
  the logging context, and raises the same 404 for "no such client" and "not
  yours" (two different answers would tell a prober which ids exist).
- EXEMPT lists the endpoints that legitimately skip the check, each with a
  reason. The adversarial test walks the real route table, calls every
  `/api/account/**` route that takes a `{cid}` with another subscriber's
  token, and fails on any 200 not listed here. An endpoint nobody registered
  is tested by default.

`/api/admin/**` isn't covered: those are founder endpoints behind the founder
token and listed in `demo_data._SENSITIVE_PREFIXES`, with no owning tenant.
"""

from __future__ import annotations

from typing import Optional

# Endpoint templates under /api/account that skip the ownership check, each with
# the reason it's safe. Anything not listed is attacked by the adversarial test.
EXEMPT: dict[str, str] = {
    # Instructions only - how to create a WordPress application password. No
    # customer data, and readable before signup.
    "/api/account/site/guide":
        "Static instructions. No client id, no customer data.",
}


class NotOwned(Exception):
    """The caller doesn't own this business. Carries no detail on purpose."""


def owner_of(client_id: str) -> Optional[str]:
    """Which subscriber owns this business, or None."""
    from . import billing

    if not client_id:
        return None
    for email in billing.all_emails():
        if client_id in billing.owned_clients(email):
            return email
    return None


def owns(email: str, client_id: str) -> bool:
    from . import billing

    if not email or not client_id:
        return False
    return client_id in billing.owned_clients(email)


def require_owner(client_id: str, token: str) -> str:
    """Resolve, authorise, and bind the tenant for logging. Raises NotOwned.

    The caller turns NotOwned into the same 404 as "no such client", so a
    prober can't tell which ids exist.
    """
    from . import billing, obs

    email = billing.resolve(token or "")
    if not email or not owns(email, client_id):
        raise NotOwned()
    # Every log line for the rest of this request carries the tenant, so a
    # cross-tenant incident can be reconstructed.
    obs.bind(tenant=client_id)
    return email
