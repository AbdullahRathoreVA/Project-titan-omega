"""The founder's login.

Two logins live here, and only one is meant to stay:

* Real accounts (``core/identity.py``): a person, a role, and a password
  hashed with PBKDF2-SHA256, with the cost stored in the hash. Organisations,
  invitations and per-customer access build on this.
* The environment gate: one ``TITAN_USERNAME`` / ``TITAN_PASSWORD`` pair
  compared against environment variables (defaults ``founder``/``titan``). A
  single-operator door with no concept of a person.

The gate retires itself. :func:`login` tries real accounts first, and once a
founder account exists the environment comparison is unreachable (see
:func:`identity_retired_the_gate`). It isn't deleted yet because
``TITAN_FOUNDER_EMAIL`` isn't set on the live deployment, and removing the
only way in at the same time as adding its replacement risks a lockout.
``/api/auth`` reports which mode is active.

Auth is only enforced when ``TITAN_REQUIRE_AUTH=1`` (set on the public
deploy). Locally it's off, so the dashboard opens straight away.
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
    # Production is never a guest deploy. This exists so shared modules (e.g. the
    # premium TTS route) can check it the same way. Only true if explicitly set.
    return os.getenv("TITAN_GUEST_MODE") == "1"


def using_demo_credentials() -> bool:
    return (os.getenv("TITAN_USERNAME"), os.getenv("TITAN_PASSWORD")) == (None, None)


def _eq(a: str, b: str) -> bool:
    """Constant-time compare that a stranger can't crash.

    ``hmac.compare_digest`` raises TypeError on a non-ASCII ``str``, so a
    username with an accent would return a 500. Encoding first avoids the
    exception without weakening the comparison.
    """
    return hmac.compare_digest((a or "").encode(), (b or "").encode())


def _secret() -> bytes:
    # A stable per-deploy secret keeps tokens valid across requests. Read through
    # core.appsecret, the only module allowed to touch TITAN_SECRET, so a missing
    # secret never falls back to a published default.
    from . import appsecret
    return appsecret.key()


def make_token(username: str) -> str:
    """Issue a session under the environment gate.

    A real session with an expiry that can be revoked, instead of a fixed
    hmac(secret, username) value that would stay valid forever.
    """
    from . import sessions
    return sessions.issue(username, kind="founder")


def identity_retired_the_gate() -> bool:
    """Has this deployment moved to real accounts?

    True once a founder account exists in ``core/identity.py``. That alone
    switches the environment comparison off; there's no flag to set.

    Returns False if the identity table can't be read. On purpose: an
    unreadable database should fail towards the founder still being able to
    sign in, not towards nobody being able to. The environment password is
    still required on that path, so it isn't a bypass.
    """
    try:
        from . import identity
        return identity.founder_exists()
    except Exception:
        return False


def login(identifier: str, password: str) -> Optional[str]:
    """Sign in as the founder. Returns a session token, or None.

    Never says which half was wrong, or whether the address exists here.
    """
    from . import sessions

    try:
        from . import identity
        token = identity.authenticate(identifier, password)
    except Exception:
        # A broken identity table mustn't take the login endpoint down; fall through
        # to the gate, which needs no database.
        token = None

    if token:
        from . import identity
        user = identity.resolve(token)
        if user and user["role"] == identity.FOUNDER:
            return token
        # A real account, but not the founder's. Members have no dashboard of their
        # own yet, so this is refused rather than given a founder session, and the
        # session just created is revoked instead of left valid.
        sessions.revoke(token)
        return None

    if identity_retired_the_gate():
        return None

    user_, pwd = credentials()
    if _eq(identifier, user_) and _eq(password, pwd):
        return sessions.issue(user_, kind="founder")
    return None


def founder_from_token(token: str) -> Optional[str]:
    """Which founder holds this token, if anyone?

    Returns the login identifier (an email under real accounts, the configured
    username under the environment gate) or None.
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
        # Written `is not None` rather than truthily so this line differs from the
        # similar check in login() above: the mutation tool replaces the first match,
        # so two guards need two distinct anchors.
        if user is not None and user["role"] == identity.FOUNDER:
            return user["email"]
        return None

    sub = sessions.subject(token, kind="founder")
    if not sub or identity_retired_the_gate():
        return None
    # The signature proves Titan issued it; this proves it was issued for the
    # account configured now. Changing TITAN_USERNAME mustn't leave tokens for the
    # old one working.
    return sub if _eq(sub, credentials()[0]) else None


def valid_token(token: str) -> bool:
    return founder_from_token(token) is not None


def revoke_token(token: str) -> bool:
    """Sign out."""
    from . import sessions
    return sessions.revoke(token)


# --- Guest (public demo) session -------------------------------------------
# One Space serves both the founder's dashboard and a public read-only demo. A
# guest token is a separate, non-privileged credential: it allows GET-only
# access, and endpoints with private business data return demo-safe sample
# content instead (see core/demo_data.py). It can never write.

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
    TITAN_DEMO_ENABLED=0 to hide it.
    """
    return os.getenv("TITAN_DEMO_ENABLED", "1") != "0"
