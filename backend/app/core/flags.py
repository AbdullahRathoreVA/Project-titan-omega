"""Feature flags, and an answer to "why is this on for them and off for me".

The brief asks for flags scoped by plan, user, tenant, environment and an
executive override. That list is five different ways for a feature to be on,
which means the interesting question is never "is it on" — it is **which of the
five decided**. A flag system you cannot interrogate is worse than no flag
system, because a support conversation about it becomes guesswork.

So :func:`is_enabled` answers the question and :func:`explain` shows the work:
every layer that was consulted, what it said, and which one won.

Resolution order, most specific first
-------------------------------------
1. **user** — an override for one person. The executive escape hatch, and the
   thing you reach for at 2am when one customer is blocked.
2. **org** — an override for one tenant.
3. **environment** — ``TITAN_FLAG_<KEY>``. Above plan on purpose: it is how a
   deployment turns something off *right now*, without a database write, when
   the database is the thing that is broken.
4. **plan** — which subscription tiers include the feature.
5. **default** — what the flag ships as.

Decisions worth defending
-------------------------
* **The flag set is closed.** An unknown key raises rather than returning
  False. A typo silently meaning "off" is how a feature disappears for
  everybody and nobody can find out why — the same reasoning that makes
  ``identity`` and ``orgs`` refuse an unknown role.
* **Overrides record who set them.** A flag flipped by nobody, at no time, is
  an unexplainable production state.
* **A missing plan is not a denied plan.** ``plans=None`` means "every plan",
  not "no plan"; a flag with no plan list should be on for everyone rather
  than silently off for everyone.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from typing import Optional

_lock = threading.RLock()

USER = "user"
ORG = "org"
SCOPES = frozenset({USER, ORG})


class FlagError(ValueError):
    """Unknown flag, or an unknown scope. Never silently false."""


class FlagDisabled(PermissionError):
    """A feature was asked to run while its flag is off.

    A distinct type from FlagError on purpose: "you named a flag that does not
    exist" is a programming mistake, and "this capability is switched off" is
    an operating decision. Callers handle them differently, and an endpoint
    that returns 500 for the second one has not implemented a kill switch, it
    has implemented a crash.
    """


@dataclass(frozen=True)
class Flag:
    key: str
    description: str
    default: bool = False
    # None means every plan. An empty frozenset would mean NO plan, which is a
    # very different thing and is why this is not defaulted to one.
    plans: Optional[frozenset] = None
    # WHERE this flag is actually consulted. Empty means NOWHERE, and that is
    # published as `enforced: false` rather than hidden.
    #
    # This field exists because every flag in this dict was unenforced for a
    # whole release. The screen said "site_fix: enabled", an operator could set
    # it to disabled, and core/site_fix.py never asked. Somebody would have
    # believed they had stopped Titan editing a live website.
    #
    # A kill switch that does not kill is worse than no kill switch: no kill
    # switch at least tells you to go and pull the plug yourself.
    enforced_at: tuple = ()


# The closed set. Adding a capability means adding it here, which is the point:
# a grep for this dict is a complete list of what can be turned on and off.
FLAGS: dict[str, Flag] = {
    "organisations": Flag(
        "organisations",
        "Teams: several people on one account, with ranked roles.",
        default=True),
    "audit_log": Flag(
        "audit_log",
        "Who did what to whom, readable by organisation administrators.",
        default=True),
    "site_fix": Flag(
        "site_fix",
        "Propose and apply fixes to a connected WordPress site.",
        default=True,
        enforced_at=("core.site_fix.propose", "core.site_fix.apply")),
    "voice": Flag(
        "voice",
        "Voice sessions and transcripts.",
        default=True,
        enforced_at=("core.voice_sessions.start",)),
    "executive_metrics": Flag(
        "executive_metrics",
        "MRR, ARR, churn and conversion, each stating whether it was measured.",
        default=True),
}


def _conn():
    from .. import persistence
    from . import db
    return db.connect(persistence.STATE_FILE)


def _require(key: str) -> Flag:
    flag = FLAGS.get(key)
    if flag is None:
        raise FlagError(f"Unknown feature flag: {key}. "
                        f"One of {sorted(FLAGS)}.")
    return flag


def _env_value(key: str) -> Optional[bool]:
    raw = os.getenv(f"TITAN_FLAG_{key.upper()}", "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    return None


def _override(key: str, scope: str, scope_id: str) -> Optional[bool]:
    if not scope_id:
        return None
    try:
        row = _conn().execute(
            "SELECT enabled FROM feature_flags WHERE key=? AND scope=?"
            " AND scope_id=?", (key, scope, scope_id)).fetchone()
    except Exception:
        return None
    return bool(row["enabled"]) if row else None


def set_override(key: str, scope: str, scope_id: str, enabled: bool,
                 set_by: str = "") -> dict:
    """Turn a flag on or off for one person or one organisation."""
    _require(key)
    if scope not in SCOPES:
        raise FlagError(f"Unknown scope: {scope}. One of {sorted(SCOPES)}.")
    if not scope_id:
        raise FlagError("An override needs something to apply to.")
    conn = _conn()
    with _lock, conn:
        conn.execute(
            "INSERT INTO feature_flags (key, scope, scope_id, enabled,"
            " set_by, set_at) VALUES (?,?,?,?,?,?)"
            " ON CONFLICT(key, scope, scope_id) DO UPDATE SET"
            " enabled=excluded.enabled, set_by=excluded.set_by,"
            " set_at=excluded.set_at",
            (key, scope, scope_id, 1 if enabled else 0, set_by or "",
             time.time()))
    return {"key": key, "scope": scope, "scope_id": scope_id,
            "enabled": bool(enabled), "set_by": set_by}


def clear_override(key: str, scope: str, scope_id: str) -> bool:
    _require(key)
    conn = _conn()
    with _lock, conn:
        cur = conn.execute(
            "DELETE FROM feature_flags WHERE key=? AND scope=? AND scope_id=?",
            (key, scope, scope_id))
        return cur.rowcount > 0


def explain(key: str, *, user_id: str = "", org_id: str = "",
            plan: str = "") -> dict:
    """Every layer that was consulted, and which one decided.

    This is the function that makes the flag system supportable. "It is off for
    this customer" is not an answer anybody can act on; "the plan layer said no
    because `site_fix` is not in the free tier" is.
    """
    flag = _require(key)
    layers = []

    user_value = _override(key, USER, user_id)
    layers.append({"layer": "user", "applies": user_id != "",
                   "value": user_value})

    org_value = _override(key, ORG, org_id)
    layers.append({"layer": "org", "applies": org_id != "",
                   "value": org_value})

    env_value = _env_value(key)
    layers.append({"layer": "environment", "applies": env_value is not None,
                   "value": env_value,
                   "variable": f"TITAN_FLAG_{key.upper()}"})

    # plans=None means every plan. Not "no plan" — see the dataclass.
    plan_value = None
    if flag.plans is not None and plan:
        plan_value = plan in flag.plans
    layers.append({"layer": "plan", "applies": plan_value is not None,
                   "value": plan_value,
                   "included_in": sorted(flag.plans) if flag.plans else None})

    layers.append({"layer": "default", "applies": True,
                   "value": flag.default})

    for layer in layers:
        if layer["value"] is not None:
            decided_by, enabled = layer["layer"], bool(layer["value"])
            break
    else:                                    # pragma: no cover - default is never None
        decided_by, enabled = "default", flag.default

    return {
        "key": key,
        "enabled": enabled,
        "decided_by": decided_by,
        "description": flag.description,
        "layers": layers,
        # Whether anything consults this flag. A switch that changes nothing
        # must say so where it is offered, not in a docstring nobody opens.
        "enforced": bool(flag.enforced_at),
        "enforced_at": list(flag.enforced_at),
        "note": (None if flag.enforced_at else
                 "No code consults this flag yet, so turning it off changes "
                 "nothing. Shown rather than hidden: a switch you believe "
                 "works is worse than one you know does not."),
    }


def is_enabled(key: str, *, user_id: str = "", org_id: str = "",
               plan: str = "") -> bool:
    return explain(key, user_id=user_id, org_id=org_id, plan=plan)["enabled"]


def require(key: str, *, user_id: str = "", org_id: str = "",
            plan: str = "") -> None:
    """Raise FlagDisabled unless this capability is switched on.

    The enforcement half. `is_enabled` returning False and nobody acting on it
    is how this module spent a whole release as decoration, so the intended way
    to gate a feature is this function, whose return value cannot be ignored by
    forgetting to write an `if`.
    """
    verdict = explain(key, user_id=user_id, org_id=org_id, plan=plan)
    if not verdict["enabled"]:
        raise FlagDisabled(
            f"{key} is switched off ({verdict['decided_by']} layer). "
            f"{FLAGS[key].description}")


def enforced(key: str) -> bool:
    """Does any code actually consult this flag?

    False means turning it off changes nothing, which a screen offering a
    switch is obliged to say out loud.
    """
    return bool(_require(key).enforced_at)


def all_flags(*, user_id: str = "", org_id: str = "", plan: str = "") -> list:
    """Every flag as it resolves for this caller, with the reason."""
    return [explain(key, user_id=user_id, org_id=org_id, plan=plan)
            for key in sorted(FLAGS)]


def overrides(key: str = "") -> list:
    """Every override currently stored. Small by design — an override is an
    exception, and a long list of them means a plan is wrong."""
    try:
        if key:
            rows = _conn().execute(
                "SELECT * FROM feature_flags WHERE key=? ORDER BY set_at DESC",
                (key,)).fetchall()
        else:
            rows = _conn().execute(
                "SELECT * FROM feature_flags ORDER BY set_at DESC").fetchall()
    except Exception:
        return []
    return [{"key": r["key"], "scope": r["scope"], "scope_id": r["scope_id"],
             "enabled": bool(r["enabled"]), "set_by": r["set_by"],
             "set_at": r["set_at"]} for r in rows]
