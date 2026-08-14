"""One place that decides whether a caller may touch a business's data.

Titan is multi-tenant: one subscriber pays for several client businesses, and
those businesses' data — audit findings, website credentials, voice
transcripts, the exact previous content of pages Titan has edited — must never
cross between subscribers.

Until now that was enforced by repeating four lines in every endpoint:

    email = billing.resolve(token)
    if not email or cid not in billing.owned_clients(email):
        raise HTTPException(404)

Every current endpoint does it correctly — I checked all of them. The problem
is structural, not present-tense: the rule lives in the endpoints, so the
enforcement is only as good as the next person's memory, and there is nothing
that fails when a new endpoint forgets. That is the same shape as the bug the
founder-endpoint guard was written for, which had already caught five leaks
including `/api/admin/clients` exposing real client contacts.

So two things live here:

**A single enforcement function.** `require_owner()` resolves the token,
checks ownership, binds the tenant to the logging context so every subsequent
log line carries it, and raises the same 404 for "no such client" and "not
yours" — distinguishing them tells a prober which ids exist.

**A declared exemption list.** An endpoint that legitimately does not need an
ownership check must say so here, with a reason. The adversarial test walks the
real route table, attacks every `/api/account/**` route that takes a `{cid}`
with a *different* subscriber's token, and fails on anything that answers 200
and is not on this list. It fails OPEN: a new endpoint that nobody registered
is attacked by default, and a leak is a failing test rather than a discovery.

`/api/admin/**` is deliberately NOT covered here. Those are founder endpoints
for Abdullah's own portfolio, behind the founder token and registered in
`demo_data._SENSITIVE_PREFIXES`; they are not subscriber-facing and have no
owning tenant to check.
"""

from __future__ import annotations

from typing import Optional

# Endpoint path templates under /api/account that do NOT take an ownership
# check, each with the reason it is safe. Anything not listed is attacked by
# the adversarial test.
EXEMPT: dict[str, str] = {
    # Instructions only — how to create a WordPress application password.
    # Contains no customer data and is deliberately readable before signup.
    "/api/account/site/guide":
        "Static instructions. No client id, no customer data.",
}


class NotOwned(Exception):
    """The caller does not own this business. Carries no detail on purpose."""


def owner_of(client_id: str) -> Optional[str]:
    """Which subscriber owns this business, or None. The single lookup."""
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

    The caller converts NotOwned into a 404 — the SAME 404 as "no such
    client", because two different answers tell a prober which ids exist.
    """
    from . import billing, obs

    email = billing.resolve(token or "")
    if not email or not owns(email, client_id):
        raise NotOwned()
    # Every log line emitted for the rest of this request now carries the
    # tenant, which is what makes a cross-tenant incident reconstructable.
    obs.bind(tenant=client_id)
    return email
