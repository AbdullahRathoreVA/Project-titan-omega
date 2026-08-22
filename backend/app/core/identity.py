"""People. Real accounts with passwords, roles and sessions.

What this replaces
------------------
``core/auth.py`` describes itself accurately: *"a single-operator gate, not a
multi-tenant identity system"*. One username and one password, compared in
**plaintext** against environment variables, defaulting to ``founder``/``titan``.
There was no concept of a *person*, so there was nothing for a role or an
organisation to attach to — which is why organisations could not be built on top
of it.

Two other stores already hash passwords properly (``billing`` for subscribers,
``clients`` for businesses). This is not a third login bolted alongside them: it
is the identity table those are being migrated onto, starting here with the
table, the hashing and the roles, so that each step can be verified in
production on its own rather than swapping out the founder's only way in
alongside everything else.

Decisions worth defending
-------------------------
* **The hash is self-describing**: ``pbkdf2_sha256$<iterations>$<salt>$<hash>``.
  The iteration count travels *with* the hash, so raising the cost later leaves
  every existing password verifiable and lets a login transparently re-hash.
  A bare constant would silently invalidate every stored password the day
  somebody edited it.
* **A missing user still costs a hash.** Verifying against a dummy hash when the
  email is unknown keeps the response time from advertising which addresses are
  registered. User enumeration is the cheap first step of every credential
  attack.
* **Disabled means disabled.** ``status`` is checked after the password, so
  turning someone off actually turns them off, and does not leak that their
  password was right.
* **Roles are a closed set.** An unknown role is refused rather than stored;
  a typo becoming a new privilege level is how authorisation bugs start.
* **The secret comes from one door** (``core/appsecret.py``), so sessions here
  cannot be signed with a key published in the repository.

Nothing here grants access on its own — issuing a session is separate from what
a session is allowed to do. Authorisation stays in ``core/tenancy.py``.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import threading
import time
import uuid
from typing import Optional

# OWASP's current floor for PBKDF2-HMAC-SHA256. Deliberately a module global
# rather than a literal: it is read at hash time and written INTO the hash, so a
# test can lower it for speed without making the stored hashes unverifiable, and
# raising it in production does not invalidate anybody.
ITERATIONS = 600_000

ALGORITHM = "pbkdf2_sha256"

FOUNDER = "founder"
MEMBER = "member"
ROLES = frozenset({FOUNDER, MEMBER})

ACTIVE = "active"
DISABLED = "disabled"

# Long enough to be worth the hashing, short enough not to push people into
# reusing one they already have written down. The generated passwords handed out
# by the founder grant flow are 16 characters, so they clear this comfortably.
MIN_PASSWORD = 12

_lock = threading.RLock()

# A syntactically valid address, not a proof of deliverability. Anything
# stricter rejects real addresses; anything looser lets "  " through.
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class IdentityError(ValueError):
    """A refusal a caller is expected to show to a human."""


def _conn():
    from .. import persistence
    from . import db
    return db.connect(persistence.STATE_FILE)


# ------------------------------------------------------------------ hashing --
def hash_password(password: str, iterations: Optional[int] = None) -> str:
    rounds = int(iterations or ITERATIONS)
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(),
                                 rounds).hex()
    return f"{ALGORITHM}${rounds}${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    """Constant-time, and never raises on a malformed stored value."""
    try:
        algo, rounds, salt, digest = (stored or "").split("$", 3)
        if algo != ALGORITHM:
            return False
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode(),
                                        salt.encode(), int(rounds)).hex()
    except Exception:
        return False
    return hmac.compare_digest(candidate, digest)


# A real hash of a value nobody can supply, used to spend the same time on an
# unknown email as on a known one. Computed once, lazily, at the CURRENT cost.
_DUMMY: Optional[str] = None


def _dummy_hash() -> str:
    global _DUMMY
    if _DUMMY is None or f"${ITERATIONS}$" not in _DUMMY:
        _DUMMY = hash_password(secrets.token_urlsafe(32))
    return _DUMMY


# ------------------------------------------------------------------- people --
def normalise_email(email: str) -> str:
    return (email or "").strip().lower()


def _row_to_public(row) -> dict:
    """Never includes the hash. The only way to leak it is to add it here."""
    return {
        "id": row["id"],
        "email": row["email"],
        "role": row["role"],
        "status": row["status"],
        "created_at": row["created_at"],
        "last_login_at": row["last_login_at"],
        "password_changed_at": row["password_changed_at"],
    }


def _require_role(role: str) -> str:
    """The one place a role is validated.

    ``create`` and ``set_role`` each carried their own copy of this check, which
    quietly weakened the mutation guard on it: the tool replaces the FIRST match
    of an anchor, so deleting the check only ever disarmed ``create``, and
    ``set_role`` was never actually tested against its own guard being gone.
    One copy, one anchor, both call sites covered.
    """
    if role not in ROLES:
        raise IdentityError(f"Unknown role: {role}. One of {sorted(ROLES)}.")
    return role


def create(email: str, password: str, role: str = MEMBER) -> dict:
    """Register a person. Raises IdentityError with a reason a human can act on."""
    email = normalise_email(email)
    if not _EMAIL.match(email):
        raise IdentityError("A valid email address is required.")
    if len(password or "") < MIN_PASSWORD:
        raise IdentityError(
            f"Password must be at least {MIN_PASSWORD} characters.")
    _require_role(role)

    now = time.time()
    conn = _conn()
    with _lock, conn:
        existing = conn.execute("SELECT id FROM users WHERE email=?",
                                (email,)).fetchone()
        if existing:
            raise IdentityError("An account with that email already exists.")
        conn.execute(
            "INSERT INTO users (id, email, pwhash, role, status, created_at,"
            " last_login_at, password_changed_at) VALUES (?,?,?,?,?,?,?,?)",
            (uuid.uuid4().hex, email, hash_password(password), role, ACTIVE,
             now, None, now))
        row = conn.execute("SELECT * FROM users WHERE email=?",
                           (email,)).fetchone()
    return _row_to_public(row)


def get(email: str) -> Optional[dict]:
    row = _conn().execute("SELECT * FROM users WHERE email=?",
                          (normalise_email(email),)).fetchone()
    return _row_to_public(row) if row else None


def get_by_id(user_id: str) -> Optional[dict]:
    """Look somebody up by id rather than address.

    `core/orgs.py` stores membership against the id, because an email address
    is a label a person may change and an id is who they are. Without this,
    every membership row would have to be resolved back through an address and
    the two would drift apart the first time one changed.
    """
    if not user_id:
        return None
    row = _conn().execute("SELECT * FROM users WHERE id=?",
                          (user_id,)).fetchone()
    return _row_to_public(row) if row else None


def authenticate(email: str, password: str) -> Optional[str]:
    """Return a session token, or None. Never says WHICH half was wrong."""
    email = normalise_email(email)
    row = _conn().execute("SELECT * FROM users WHERE email=?",
                          (email,)).fetchone()

    # Spend the hashing time either way: a fast "no" for unknown addresses and a
    # slow one for known addresses tells an attacker who has an account here.
    if not row:
        verify_password(password or "", _dummy_hash())
        return None
    if not verify_password(password or "", row["pwhash"]):
        return None
    # Checked AFTER the password so a disabled account does not answer faster
    # than a wrong password, which would confirm the address exists.
    if row["status"] != ACTIVE:
        return None

    conn = _conn()
    with _lock, conn:
        conn.execute("UPDATE users SET last_login_at=? WHERE id=?",
                     (time.time(), row["id"]))

    from . import sessions
    return sessions.issue(email, kind="user")


def resolve(token: str) -> Optional[dict]:
    """Who is this token, if anybody, right now?

    A valid signature is not enough. The user must still exist and still be
    active — deleting or disabling somebody has to actually revoke their access,
    not wait for a fortnight-long token to expire.
    """
    from . import sessions
    email = sessions.subject(token or "", kind="user")
    if not email:
        return None
    user = get(email)
    if not user or user["status"] != ACTIVE:
        return None
    return user


def set_password(email: str, password: str) -> bool:
    if len(password or "") < MIN_PASSWORD:
        raise IdentityError(
            f"Password must be at least {MIN_PASSWORD} characters.")
    conn = _conn()
    now = time.time()
    with _lock, conn:
        cur = conn.execute(
            "UPDATE users SET pwhash=?, password_changed_at=? WHERE email=?",
            (hash_password(password), now, normalise_email(email)))
        return cur.rowcount > 0


def set_role(email: str, role: str) -> bool:
    _require_role(role)
    conn = _conn()
    with _lock, conn:
        cur = conn.execute("UPDATE users SET role=? WHERE email=?",
                           (role, normalise_email(email)))
        return cur.rowcount > 0


def set_status(email: str, status: str) -> bool:
    if status not in (ACTIVE, DISABLED):
        raise IdentityError(f"Unknown status: {status}.")
    conn = _conn()
    with _lock, conn:
        cur = conn.execute("UPDATE users SET status=? WHERE email=?",
                           (status, normalise_email(email)))
        return cur.rowcount > 0


def all_users() -> list[dict]:
    rows = _conn().execute(
        "SELECT * FROM users ORDER BY created_at DESC").fetchall()
    return [_row_to_public(r) for r in rows]


def count(role: Optional[str] = None) -> int:
    if role:
        row = _conn().execute("SELECT COUNT(*) AS n FROM users WHERE role=?",
                              (role,)).fetchone()
    else:
        row = _conn().execute("SELECT COUNT(*) AS n FROM users").fetchone()
    return int(row["n"])


def stats() -> dict:
    """For the founder screen. Counts are derived from the table, so they are
    measured; nothing here is estimated."""
    rows = _conn().execute(
        "SELECT role, status, COUNT(*) AS n FROM users"
        " GROUP BY role, status").fetchall()
    by_role: dict[str, int] = {}
    by_status: dict[str, int] = {}
    for r in rows:
        by_role[r["role"]] = by_role.get(r["role"], 0) + r["n"]
        by_status[r["status"]] = by_status.get(r["status"], 0) + r["n"]
    return {
        "users": sum(by_role.values()),
        "by_role": by_role,
        "by_status": by_status,
        "algorithm": ALGORITHM,
        "iterations": ITERATIONS,
        # Says out loud that identity is only as durable as the database.
        "durable": bool(_durable()),
    }


def _durable() -> bool:
    try:
        from . import db
        return bool(db.stats().get("durable"))
    except Exception:
        return False


# ------------------------------------------------------------- the founder --
# How the cutover from ``core/auth.py`` actually happens.
#
# ``core/auth.py`` compares one username and one password against environment
# variables in plaintext. Deleting that comparison outright is the obvious move
# and it is the wrong one: the address this table needs is not set on the live
# deployment yet, so a hard cut would leave the founder with no way into his own
# dashboard on a site that is already serving traffic.
#
# So the gate retires ITSELF. Once a founder account exists here, the
# environment comparison stops being reachable — permanently, with no second
# deploy and no flag anybody has to remember to flip. Until then it keeps
# working, and ``/api/auth`` says which mode is in force, so the remaining step
# is visible in the product rather than only in a handover document.

FOUNDER_EMAIL_VAR = "TITAN_FOUNDER_EMAIL"


def configured_founder_email() -> Optional[str]:
    """The address the founder signs in with, or None if the host has not said.

    ``TITAN_USERNAME`` is accepted only when it already IS an address. Seeding a
    synthetic ``<username>@titan.local`` to satisfy the validator was considered
    and rejected: an address nobody chose, that no mail ever reaches, is
    impossible to reason about later and would quietly become the account
    somebody eventually tries to send a password reset to.
    """
    for var in (FOUNDER_EMAIL_VAR, "TITAN_USERNAME"):
        candidate = normalise_email(os.getenv(var, ""))
        if _EMAIL.match(candidate):
            return candidate
    return None


def founder_exists() -> bool:
    """Is there a real founder account?

    This one fact is what retires the environment gate, so it answers False on
    any error rather than raising: a database that cannot be read must fail
    towards the founder still being able to sign in, never towards nobody
    being able to. The environment password is still required either way, so
    this is not a bypass.
    """
    try:
        row = _conn().execute(
            "SELECT 1 FROM users WHERE role=? AND status=? LIMIT 1",
            (FOUNDER, ACTIVE)).fetchone()
        return row is not None
    except Exception:
        return False


def ensure_founder() -> dict:
    """Seed the founder account from the environment. Idempotent, never raises.

    Called once from the application lifespan. Returns what it did in terms a
    status screen can show, and **never echoes the password** — not its value
    and not its length.

    Deliberate: the password is read only when the account is CREATED. Once the
    row exists the database is authoritative, so changing ``TITAN_PASSWORD`` on
    the host cannot silently overwrite a password that was changed inside the
    product. On a host with no persistent storage the table is empty after every
    rebuild and the environment seeds it again, which is exactly the behaviour
    that keeps a free-tier deployment usable.
    """
    email = configured_founder_email()
    if not email:
        return {"mode": "legacy", "seeded": False, "email": None,
                "reason": (f"{FOUNDER_EMAIL_VAR} is not set to a valid email "
                           "address, so there is no account to sign in to. The "
                           "environment gate in core/auth.py is still in use.")}
    try:
        current = get(email)
    except Exception as exc:
        return {"mode": "legacy", "seeded": False, "email": email,
                "reason": f"The identity table could not be read: {exc}"}

    # Named `current`, not `existing`, so this line is a unique mutation anchor:
    # `create()` above has an `if existing:` of its own and the mutation tool
    # replaces the FIRST match it finds.
    if current:
        # Somebody may have registered this address as a member first. The host
        # is the authority on who the founder is, so promote rather than refuse.
        if current["role"] != FOUNDER:
            set_role(email, FOUNDER)
        if current["status"] != ACTIVE:
            set_status(email, ACTIVE)
        return {"mode": "identity", "seeded": False, "email": email,
                "reason": "The founder account already exists."}

    password = os.getenv("TITAN_PASSWORD", "")
    if len(password) < MIN_PASSWORD:
        return {"mode": "legacy", "seeded": False, "email": email,
                "reason": (f"{FOUNDER_EMAIL_VAR} is set, but TITAN_PASSWORD is "
                           f"missing or shorter than {MIN_PASSWORD} characters. "
                           "No account was created: seeding the founder with a "
                           "weak or default password would be worse than "
                           "leaving the old gate in place.")}
    try:
        create(email, password, role=FOUNDER)
    except IdentityError as exc:
        return {"mode": "legacy", "seeded": False, "email": email,
                "reason": str(exc)}
    except Exception as exc:
        return {"mode": "legacy", "seeded": False, "email": email,
                "reason": f"The founder account could not be created: {exc}"}

    return {"mode": "identity", "seeded": True, "email": email,
            "reason": "The founder account was created from the environment."}


def mode() -> dict:
    """Which login is in force, right now — measured, not remembered.

    **Never carries the founder's address.** This is read by ``/api/auth``,
    which answers before anybody has signed in; publishing the one address that
    can administer the system would hand every passer-by the first half of the
    credentials.
    """
    active = founder_exists()
    return {
        "mode": "identity" if active else "legacy",
        "founder_email_configured": configured_founder_email() is not None,
        "founder_account_exists": active,
        "environment_gate_reachable": not active,
    }
