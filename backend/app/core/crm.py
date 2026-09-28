"""A customer's own leads, scoped to their account.

The leads pipeline (create, status, stages, discovery, research, outreach
drafting) was founder-only, with `STORE.leads` a flat dict and no owner
field. A leads table shared by every customer is one missing filter away
from showing a business its competitor's pipeline, so ownership is handled
in one place here.

Every lead carries `account`, the billing email of the subscriber who owns
it:

  * `account: ""` is the founder's own prospecting pipeline. Older leads
    have no field at all, and `owner_of()` reads a missing field as the
    founder's, so existing leads stay where they are without a migration.
  * Any other value is a subscriber, who only sees their own.

`visible_to()` is the one function that decides what a caller may see, like
`tenancy.require_owner` for businesses. Every read here goes through it,
including counts, since a count over the unfiltered set leaks how many leads
someone else has.
"""

from __future__ import annotations

import threading
from typing import Optional

_lock = threading.RLock()

# The founder's own pipeline. An empty owner means the founder, not
# "unowned" or "public".
FOUNDER = ""

# Same vocabulary as the founder pipeline, so a status means the same thing
# whichever screen created the lead.
STATUSES = ("new", "contacted", "replied", "qualified", "won", "lost")


class NotYours(PermissionError):
    """Someone asked for a lead that isn't theirs. "Not yours" and "no such
    lead" get the same answer, otherwise the difference reveals other
    people's records.
    """


def owner_of(lead: dict) -> str:
    """Who owns this lead. A missing field means the founder."""
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
    """The lead, or NotYours. Same refusal whether it exists or not."""
    lead = leads.get(lead_id)
    if not lead or not owns(lead, account):
        raise NotYours("No such lead")
    return lead


def new_lead(*, lead_id: str, account: str, name: str, source: str = "manual",
             contact: str = "", note: str = "", website: str = "",
             created_at: str = "", updated_at: str = "") -> dict:
    """One shape for a lead, wherever it was created.

    Built here rather than at each route so leads from customers and from
    discovery can't drift apart, and so `account` can't be forgotten; a lead
    created without an owner would become the founder's.
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
    """What needs a person, and why.

    Each entry names the lead, the reason and what to do; a bare list just
    teaches people to clear it without reading. Nothing is guessed: a lead
    with no contact detail is a fact about the record.
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
    """Pipeline figures, each a real count.

    No conversion rate when there's nothing to divide by: a rate over zero
    leads isn't 0%, it's unmeasured.
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
