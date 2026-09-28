"""Organisations: several people sharing one account with different privileges.

Existing levels:

* ``core/billing.py`` - a subscriber: one email, one plan, one password.
* ``core/clients.py`` - the businesses that subscriber manages.
* ``core/tenancy.py`` - the rule that one subscriber can't read another's.

This adds people, built on ``core/identity.py``, so two people can share an
account, a colleague can get read-only access, and roles have something to
attach to.

Billing isn't migrated onto organisations yet. That path takes money, so
organisations are wired into their own endpoints and proven first.

Roles
-----
===================  ===========================================================
Role name            Here
===================  ===========================================================
Executive            ``core/identity.FOUNDER`` - administers the whole SaaS,
                     not an organisation. A separate axis.
Administrator        ``ADMIN``   - everything except deleting the organisation
Manager              ``MANAGER`` - may manage work, not who has access
Team Member          ``MEMBER``  - may do the work
Customer / User      ``VIEWER``  - read-only
(no equivalent)      ``OWNER``   - the executive of one organisation
===================  ===========================================================

* Roles are ranked and compared in one place. ``require_member`` is the only
  thing that decides whether a caller may act, like
  ``tenancy.require_owner`` for businesses.
* An unknown role is refused, never stored, so a typo can't become a new
  privilege level (same as ``identity._require_role``).
* An organisation can never lose its last owner. Removing or demoting the
  final owner would leave it impossible to administer, so both refuse. This
  invariant is mutation-guarded.
* Membership is keyed on user id, not email; an address can change.
* "Not a member" and "no such organisation" raise the same refusal, so a
  prober can't tell which ids exist.

Nothing here grants access by itself. It answers "may this person act on
this organisation at this level", and the endpoint turns a refusal into a
404.
"""

from __future__ import annotations

import re
import threading
import time
import uuid
from typing import Optional

OWNER = "owner"
ADMIN = "admin"
MANAGER = "manager"
MEMBER = "member"
VIEWER = "viewer"

# Ordered on purpose. Checks ask "at least this much", never "exactly this",
# so a new role only needs a rank.
RANK: dict[str, int] = {
    VIEWER: 0,
    MEMBER: 1,
    MANAGER: 2,
    ADMIN: 3,
    OWNER: 4,
}
ROLES = frozenset(RANK)

ACTIVE = "active"
SUSPENDED = "suspended"
STATUSES = frozenset({ACTIVE, SUSPENDED})

_lock = threading.RLock()

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


class OrgError(ValueError):
    """A refusal a caller is expected to show to a human."""


class NotAMember(Exception):
    """Not a member, not senior enough, or no such organisation.

    Carries no detail on purpose: the endpoint turns all of these into the
    same 404, so a prober can't tell which ids exist.
    """


def _conn():
    from .. import persistence
    from . import db
    return db.connect(persistence.STATE_FILE)


def _require_role(role: str) -> str:
    """The one place a role is validated (see identity._require_role)."""
    if role not in ROLES:
        raise OrgError(f"Unknown role: {role}. One of {sorted(ROLES)}.")
    return role


def slugify(name: str) -> str:
    slug = _SLUG_STRIP.sub("-", (name or "").strip().lower()).strip("-")
    return slug[:60]


# ------------------------------------------------------------ the org --
def create(name: str, owner_user_id: str, created_by: str = "") -> dict:
    """Register an organisation and seat its first owner, atomically.

    Both rows or neither: an organisation with no owner is the state the
    last-owner rule exists to prevent, so a half-finished create mustn't
    reach it either.
    """
    name = (name or "").strip()
    if not name:
        raise OrgError("An organisation needs a name.")
    if not owner_user_id:
        raise OrgError("An organisation needs an owner.")

    from . import identity
    if not identity.get_by_id(owner_user_id):
        raise OrgError("No such user, so there is nobody to own this.")

    slug = slugify(name)
    if not slug:
        raise OrgError("That name has no letters or digits in it.")

    now = time.time()
    org_id = "org_" + uuid.uuid4().hex[:16]
    conn = _conn()
    with _lock, conn:
        if conn.execute("SELECT 1 FROM orgs WHERE slug=?", (slug,)).fetchone():
            raise OrgError(f"An organisation named '{name}' already exists.")
        conn.execute(
            "INSERT INTO orgs (id, name, slug, status, created_at, created_by)"
            " VALUES (?,?,?,?,?,?)",
            (org_id, name, slug, ACTIVE, now, created_by or ""))
        conn.execute(
            "INSERT INTO org_members (org_id, user_id, role, added_at)"
            " VALUES (?,?,?,?)", (org_id, owner_user_id, OWNER, now))
    return get(org_id)


def _row_to_public(row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "slug": row["slug"],
        "status": row["status"],
        "created_at": row["created_at"],
        "created_by": row["created_by"],
    }


def get(org_id: str) -> Optional[dict]:
    row = _conn().execute("SELECT * FROM orgs WHERE id=?",
                          (org_id or "",)).fetchone()
    return _row_to_public(row) if row else None


def by_slug(slug: str) -> Optional[dict]:
    row = _conn().execute("SELECT * FROM orgs WHERE slug=?",
                          (slugify(slug),)).fetchone()
    return _row_to_public(row) if row else None


def all_orgs() -> list[dict]:
    rows = _conn().execute(
        "SELECT * FROM orgs ORDER BY created_at DESC").fetchall()
    return [_row_to_public(r) for r in rows]


def set_status(org_id: str, status: str) -> bool:
    if status not in STATUSES:
        raise OrgError(f"Unknown status: {status}.")
    conn = _conn()
    with _lock, conn:
        cur = conn.execute("UPDATE orgs SET status=? WHERE id=?",
                           (status, org_id))
        return cur.rowcount > 0


# ------------------------------------------------------- membership --
def role_of(org_id: str, user_id: str) -> Optional[str]:
    if not org_id or not user_id:
        return None
    row = _conn().execute(
        "SELECT role FROM org_members WHERE org_id=? AND user_id=?",
        (org_id, user_id)).fetchone()
    return row["role"] if row else None


def is_member(org_id: str, user_id: str) -> bool:
    return role_of(org_id, user_id) is not None


def owner_count(org_id: str) -> int:
    row = _conn().execute(
        "SELECT COUNT(*) AS n FROM org_members WHERE org_id=? AND role=?",
        (org_id, OWNER)).fetchone()
    return int(row["n"])


def add_member(org_id: str, user_id: str, role: str = MEMBER) -> dict:
    _require_role(role)
    from . import identity
    if not get(org_id):
        raise OrgError("No such organisation.")
    if not identity.get_by_id(user_id):
        raise OrgError("No such user.")

    conn = _conn()
    with _lock, conn:
        existing = conn.execute(
            "SELECT 1 FROM org_members WHERE org_id=? AND user_id=?",
            (org_id, user_id)).fetchone()
        if existing:
            raise OrgError("That person is already in this organisation.")
        conn.execute(
            "INSERT INTO org_members (org_id, user_id, role, added_at)"
            " VALUES (?,?,?,?)", (org_id, user_id, role, time.time()))
    return {"org_id": org_id, "user_id": user_id, "role": role}


def set_member_role(org_id: str, user_id: str, role: str) -> bool:
    """Change what someone may do. Refuses to demote the last owner.

    An organisation whose only owner becomes a viewer can't be administered
    by anyone, including the person who did it.
    """
    _require_role(role)
    conn = _conn()
    with _lock, conn:
        current = role_of(org_id, user_id)
        if current is None:
            return False
        if current == OWNER and role != OWNER and owner_count(org_id) <= 1:
            raise OrgError(
                "This is the only owner. Make somebody else an owner first, "
                "or the organisation would be left with nobody who can "
                "administer it.")
        cur = conn.execute(
            "UPDATE org_members SET role=? WHERE org_id=? AND user_id=?",
            (role, org_id, user_id))
        return cur.rowcount > 0


def remove_member(org_id: str, user_id: str) -> bool:
    """Remove someone. Refuses to remove the last owner, for the same reason
    ``set_member_role`` refuses to demote them.
    """
    conn = _conn()
    with _lock, conn:
        current = role_of(org_id, user_id)
        if current is None:
            return False
        if current == OWNER and owner_count(org_id) <= 1:
            raise OrgError(
                "This is the only owner. Make somebody else an owner first.")
        cur = conn.execute(
            "DELETE FROM org_members WHERE org_id=? AND user_id=?",
            (org_id, user_id))
        return cur.rowcount > 0


def members(org_id: str) -> list[dict]:
    """Who's in this organisation. Joins identity so a screen can show a person
    rather than an id; never returns a password hash, since ``identity`` has
    no function that exposes one.
    """
    from . import identity
    rows = _conn().execute(
        "SELECT * FROM org_members WHERE org_id=? ORDER BY added_at",
        (org_id or "",)).fetchall()
    out = []
    for r in rows:
        user = identity.get_by_id(r["user_id"])
        out.append({
            "user_id": r["user_id"],
            "role": r["role"],
            "added_at": r["added_at"],
            "email": user["email"] if user else None,
            "status": user["status"] if user else None,
        })
    return out


def orgs_for(user_id: str) -> list[dict]:
    """Every organisation this person belongs to, with their role in each.
    This is the only list an ordinary member should see.
    """
    rows = _conn().execute(
        "SELECT o.*, m.role AS member_role FROM orgs o"
        " JOIN org_members m ON m.org_id = o.id"
        " WHERE m.user_id=? ORDER BY o.created_at DESC",
        (user_id or "",)).fetchall()
    out = []
    for r in rows:
        rec = _row_to_public(r)
        rec["role"] = r["member_role"]
        out.append(rec)
    return out


# ---------------------------------------------------- authorisation --
def require_member(org_id: str, user_id: str, minimum: str = VIEWER) -> str:
    """The single gate. Returns the caller's role, or raises NotAMember.

    Ranked, not equality-matched: an owner passes every check an admin
    passes. A suspended organisation refuses everyone, so suspending actually
    suspends rather than just hiding it from a list.
    """
    _require_role(minimum)
    org = get(org_id)
    if not org or org["status"] != ACTIVE:
        raise NotAMember()
    role = role_of(org_id, user_id)
    if role is None or RANK[role] < RANK[minimum]:
        raise NotAMember()
    from . import obs
    # Like tenancy.require_owner: log lines need the tenant so a cross-tenant
    # incident can be reconstructed.
    obs.bind(tenant=org_id)
    return role


def stats() -> dict:
    """Counts taken from the tables."""
    orgs_n = int(_conn().execute("SELECT COUNT(*) AS n FROM orgs")
                 .fetchone()["n"])
    rows = _conn().execute(
        "SELECT role, COUNT(*) AS n FROM org_members GROUP BY role").fetchall()
    return {
        "organisations": orgs_n,
        "memberships": sum(int(r["n"]) for r in rows),
        "by_role": {r["role"]: int(r["n"]) for r in rows},
        "roles": sorted(ROLES, key=lambda r: RANK[r]),
    }
