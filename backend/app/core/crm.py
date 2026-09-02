"""A customer's own leads. Tenant-scoped, and structurally so.

Titan has had a working leads pipeline since early on — create, status, stages,
discovery, research, outreach drafting. Every route reaching it is FOUNDER
ONLY, and `STORE.leads` is one flat dict with no owner field at all. So the
product could find leads for Abdullah and for nobody who paid.

That is the gap this closes. It is also the most dangerous kind of change in
this codebase, because a leads table shared by every customer is one missing
filter away from showing one business its competitor's pipeline.

THE OWNERSHIP RULE, AND WHY IT IS SHAPED LIKE THIS

Every lead carries `account`: the billing email of the subscriber who owns it.

  * `account: ""` means the FOUNDER's own prospecting pipeline.

Existing leads have no field at all, and `owner_of()` reads a missing field as
the founder's. That is deliberate and it is the whole migration: Abdullah's
pipeline was created before customers existed, it is his, and nothing in here
moves it. A migration that reassigned his leads to the first customer who
signed up would be silent and unrecoverable.

  * Any other value is a subscriber, and a subscriber sees only their own.

`visible_to()` is the ONE function that decides what a caller may see, for the
same reason `tenancy.require_owner` is the one gate for businesses: a filter
written at each call site is a filter missing from one of them. Every read in
this module goes through it, including the counts, because a count computed
over the unfiltered set leaks how many leads somebody else has.
"""

from __future__ import annotations

import threading
from typing import Optional

_lock = threading.RLock()

# The founder's own pipeline. An empty owner is not "unowned" — it is his, and
# it is written down here so nobody later reads the empty string as "public".
FOUNDER = ""

# Mirrors the founder pipeline's vocabulary so one lead cannot mean two things
# depending on which screen created it.
STATUSES = ("new", "contacted", "replied", "qualified", "won", "lost")


class NotYours(PermissionError):
    """Somebody asked for a lead that is not theirs. Never answered with the
    lead, and never with a different message depending on whether it exists —
    "not yours" and "no such lead" must be indistinguishable or the difference
    enumerates other people's records."""


def owner_of(lead: dict) -> str:
    """Who owns this lead. A missing field is the founder's, not nobody's."""
    return str((lead or {}).get("account") or FOUNDER)


def owns(lead: dict, account: str) -> bool:
    return owner_of(lead) == (account or FOUNDER)


def visible_to(leads: dict, account: str) -> list:
    """Every lead this caller may see, and nothing else.

    The single filter. Counts, funnels and searches all read from this rather
    than from `leads`, because a count over the unfiltered set tells one
    customer how many leads another has.
    """
    account = account or FOUNDER
    return [dict(lead) for lead in leads.values() if owns(lead, account)]


def require_owned(leads: dict, lead_id: str, account: str) -> dict:
    """The lead, or NotYours. Refuses identically whether it exists or not."""
    lead = leads.get(lead_id)
    if not lead or not owns(lead, account):
        raise NotYours("No such lead")
    return lead


def new_lead(*, lead_id: str, account: str, name: str, source: str = "manual",
             contact: str = "", note: str = "", website: str = "",
             created_at: str = "", updated_at: str = "") -> dict:
    """One shape for a lead, wherever it was created.

    Built here rather than inline at each route so a lead made by a customer
    and a lead made by discovery cannot drift into two shapes — and, more
    importantly, so `account` cannot be forgotten at one of them. A lead
    created without an owner would silently become the founder's.
    """
    return {
        "id": lead_id,
        "account": account or FOUNDER,
        "name": (name or "").strip()[:80],
        "source": (source or "manual").lower()[:30],
        "contact": (contact or "").strip()[:200],
        "note": (note or "").strip()[:300],
        "website": (website or "").strip()[:300],
        "status": "new",
        "stage_reached": 0,
        "created_at": created_at,
        "updated_at": updated_at,
    }


def counts(items: list) -> dict:
    """Status counts over a list the caller may already see."""
    return {status: sum(1 for lead in items if lead.get("status") == status)
            for status in STATUSES}


def attention(items: list, *, now_iso: str = "") -> list:
    """What needs a person, and WHY — never a bare list.

    Modelled on the CRM's follow-up engine: an item that does not say why it is
    here teaches somebody to clear the list rather than read it. Each entry
    names the lead, the reason and what to do, and nothing is invented — a lead
    with no contact detail is a fact about the record, not a guess about the
    business.
    """
    out = []
    for lead in items:
        if lead.get("status") in ("won", "lost"):
            continue
        if not (lead.get("contact") or "").strip():
            out.append({
                "lead_id": lead.get("id"), "name": lead.get("name"),
                "reason": "no contact detail",
                "why_it_matters": "Nothing can be sent to this lead.",
                "next": "Add an email address or a profile link.",
            })
        if lead.get("status") == "new" and lead.get("stage_reached", 0) == 0:
            out.append({
                "lead_id": lead.get("id"), "name": lead.get("name"),
                "reason": "never contacted",
                "why_it_matters": "It has been filed and nothing has happened.",
                "next": "Draft an approach, or mark it lost and move on.",
            })
    return out


def stats(items: list) -> dict:
    """Pipeline figures, each of them a real count.

    No conversion rate is published when there is nothing to divide by. A rate
    over zero leads is not 0% — it is a number nobody measured, and this
    codebase says so rather than showing a reassuring zero.
    """
    total = len(items)
    by_status = counts(items)
    won = by_status.get("won", 0)
    closed = won + by_status.get("lost", 0)
    return {
        "total": total,
        "counts": by_status,
        "needs_attention": len(attention(items)),
        "win_rate": {
            "value": round(won / closed, 4) if closed else None,
            "measured": bool(closed),
            "reason": None if closed else
                      "No lead has been won or lost yet, so there is nothing "
                      "to compute a rate from.",
        },
    }
