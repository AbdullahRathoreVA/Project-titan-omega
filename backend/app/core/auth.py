"""Lightweight login for the deployed dashboard.

Credentials are read from environment variables at deploy time — they are NEVER
hardcoded in the repo (a password committed to git is a public password). Set
``TITAN_USERNAME`` and ``TITAN_PASSWORD`` on your host; until you do, a clearly
labelled demo login is used.

Auth is only enforced when ``TITAN_REQUIRE_AUTH=1`` (you set this on the public
deploy). Locally it's off, so the dashboard opens with no friction.

This is a single-operator gate, not a multi-tenant identity system — good enough
to keep your public URL private, and honest about what it is.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from typing import Tuple

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


def _secret() -> bytes:
    # A stable per-deploy secret keeps tokens valid across requests. Read
    # through core.appsecret, which is the ONLY module allowed to touch
    # TITAN_SECRET: the fallback that used to live here ("titan-omega-change-me")
    # is in the public git history, so on a deployment with the variable unset
    # anyone could mint a founder token.
    from . import appsecret
    return appsecret.key()


def make_token(username: str) -> str:
    """Issue a founder session.

    Previously this was hmac(secret, username): the same string on every call,
    with no expiry and nothing to revoke. A token copied out of a browser was
    valid forever, and the only way to invalidate it was to rotate
    TITAN_SECRET and sign out of everything at once.
    """
    from . import sessions
    return sessions.issue(username, kind="founder")


def check_login(username: str, password: str) -> bool:
    user, pwd = credentials()
    return hmac.compare_digest(username, user) and hmac.compare_digest(password, pwd)


def valid_token(token: str) -> bool:
    from . import sessions
    sub = sessions.subject(token, kind="founder")
    if not sub:
        return False
    # The signature proves Titan issued it; this proves it was issued for the
    # account that is configured NOW. Changing TITAN_USERNAME must not leave
    # tokens for the old one working.
    user, _ = credentials()
    return hmac.compare_digest(sub, user)


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
