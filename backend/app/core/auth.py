"""The founder's way in.

Two logins live here, and only one of them is meant to survive.

* **Real accounts** (``core/identity.py``) — a person, a role, and a password
  hashed with PBKDF2-SHA256 at a cost stored inside the hash. This is what
  organisations, invitations and per-customer access get built on.
* **The environment gate** — one ``TITAN_USERNAME`` and one ``TITAN_PASSWORD``
  compared against environment variables, defaulting to ``founder``/``titan``.
  A single-operator door with no concept of a *person*, which is precisely why
  nothing could ever be built on top of it.

**The gate retires itself.** :func:`login` tries real accounts first, and the
moment a founder account exists the environment comparison becomes unreachable
— see :func:`identity_retired_the_gate`. It was not simply deleted, because the
address it hands over to (``TITAN_FOUNDER_EMAIL``) is not set on the live
deployment yet, and removing the founder's only way into a site that is already
serving traffic, in the same change that introduces its replacement, is how you
end up locked out of production. ``/api/auth`` reports which mode is in force,
so the one remaining step is visible in the product rather than only in a
handover document.

Auth is only enforced when ``TITAN_REQUIRE_AUTH=1`` (you set this on the public
deploy). Locally it's off, so the dashboard opens with no friction.
"""

from __future__ import annotations

import hmac
import os
from typing import Optional, Tuple

DEMO_USER = "founder"
DEMO_PASS = "titan"  # placeholder; override with TITAN_PASSWORD on deploy


def credentials() -> Tuple[str, str]:
    return os.getenv("TITAN_USERNAME", DEMO_USER), os.getenv("TITAN_PASSWORD", DEMO_PASS)


def require_auth() -> bool:
    return os.getenv("TITAN_REQUIRE_AUTH") == "1"


def guest_mode() -> bool:
    # Production is never a guest deploy; present so shared modules (e.g. the
    # premium-TTS route) can check it uniformly. Only true if explicitly set.
    return os.getenv("TITAN_GUEST_MODE") == "1"


def using_demo_credentials() -> bool:
    return (os.getenv("TITAN_USERNAME"), os.getenv("TITAN_PASSWORD")) == (None, None)


def _eq(a: str, b: str) -> bool:
    """Constant-time compare that a stranger cannot crash.

    ``hmac.compare_digest`` raises TypeError on a non-ASCII ``str``, so posting
    a username with an accent in it used to come back as a 500 from the login
    endpoint — which both looks like a fault and confirms to the sender that
    what they typed reached the comparison. Encoding first removes the
    exception without weakening the comparison.
    """
    return hmac.compare_digest((a or "").encode(), (b or "").encode())


def _secret() -> bytes:
    # A stable per-deploy secret keeps tokens valid across requests. Read
    # through core.appsecret, which is the ONLY module allowed to touch
    # TITAN_SECRET: the fallback that used to live here ("titan-omega-change-me")
    # is in the public git history, so on a deployment with the variable unset
    # anyone could mint a founder token.
    from . import appsecret
    return appsecret.key()


def make_token(username: str) -> str:
    """Issue a session under the environment gate.

    Previously this was hmac(secret, username): the same string on every call,
    with no expiry and nothing to revoke. A token copied out of a browser was
    valid forever, and the only way to invalidate it was to rotate
    TITAN_SECRET and sign out of everything at once.
    """
    from . import sessions
    return sessions.issue(username, kind="founder")


def identity_retired_the_gate() -> bool:
    """Has this deployment moved to real accounts?

    True once a founder account exists in ``core/identity.py``. That single
    fact is what switches the environment comparison off — there is no flag to
    set and no second deploy to remember.

    Answers False if the identity table cannot be read. That direction is
    deliberate: an unreadable database must fail towards the founder still
    being able to sign in, never towards nobody being able to. The environment
    password is still required on that path, so this is not a bypass.
    """
    try:
        from . import identity
        return identity.founder_exists()
    except Exception:
        return False


def login(identifier: str, password: str) -> Optional[str]:
    """Sign in as the founder. Returns a session token, or None.

    Never says which half was wrong, and never says whether the address is one
    that exists here.
    """
    from . import sessions

    try:
        from . import identity
        token = identity.authenticate(identifier, password)
    except Exception:
        # A broken identity table must not take the login endpoint down with
        # it; fall through to the gate, which needs no database.
        token = None

    if token:
        from . import identity
        user = identity.resolve(token)
        if user and user["role"] == identity.FOUNDER:
            return token
        # A real account, but not the founder's. Members have no dashboard of
        # their own yet, so this is refused rather than handed a founder
        # session — and the session just minted is thrown away rather than left
        # valid for a fortnight.
        sessions.revoke(token)
        return None

    if identity_retired_the_gate():
        return None

    user_, pwd = credentials()
    if _eq(identifier, user_) and _eq(password, pwd):
        return sessions.issue(user_, kind="founder")
    return None


def founder_from_token(token: str) -> Optional[str]:
    """Who is the founder holding this token, if anybody?

    Returns the login identifier — an email address under real accounts, the
    configured username under the environment gate — or None.
    """
    if not token:
        return None
    from . import sessions

    # Real accounts first: this is the path everything moves to.
    if sessions.subject(token, kind="user"):
        try:
            from . import identity
            user = identity.resolve(token)
        except Exception:
            return None
        # Spelled `is not None` rather than truthily, so this line differs from
        # the identical-looking check in login() above — the mutation tool
        # replaces the first match, so two guards need two anchors.
        if user is not None and user["role"] == identity.FOUNDER:
            return user["email"]
        return None

    sub = sessions.subject(token, kind="founder")
    if not sub or identity_retired_the_gate():
        return None
    # The signature proves Titan issued it; this proves it was issued for the
    # account that is configured NOW. Changing TITAN_USERNAME must not leave
    # tokens for the old one working.
    return sub if _eq(sub, credentials()[0]) else None


def valid_token(token: str) -> bool:
    return founder_from_token(token) is not None


def revoke_token(token: str) -> bool:
    """Sign out. Now actually possible."""
    from . import sessions
    return sessions.revoke(token)


# --- Guest (public demo) session -------------------------------------------
# One Space serves BOTH the founder's real dashboard and a public read-only
# demo. A guest token is a distinct, non-privileged credential: it unlocks
# GET-only access, and every endpoint carrying private business data is served
# demo-safe sample content instead (see core/demo_data.py). It can never write.

GUEST_USER = "__titan_guest__"


def make_guest_token() -> str:
    """A demo session. Read-only, so it expires sooner than a founder's."""
    from . import sessions
    return sessions.issue(GUEST_USER, kind="guest", ttl=sessions.GUEST_TTL)


def valid_guest_token(token: str) -> bool:
    from . import sessions
    return sessions.subject(token, kind="guest") == GUEST_USER


def guest_enabled() -> bool:
    """Public demo button on the login screen. On by default; set
    TITAN_DEMO_ENABLED=0 to hide it entirely."""
    return os.getenv("TITAN_DEMO_ENABLED", "1") != "0"
