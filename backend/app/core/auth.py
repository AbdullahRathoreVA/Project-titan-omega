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


def using_demo_credentials() -> bool:
    return (os.getenv("TITAN_USERNAME"), os.getenv("TITAN_PASSWORD")) == (None, None)


def _secret() -> bytes:
    # A stable per-deploy secret keeps tokens valid across requests.
    return os.getenv("TITAN_SECRET", "titan-omega-change-me").encode()


def make_token(username: str) -> str:
    return hmac.new(_secret(), username.encode(), hashlib.sha256).hexdigest()


def check_login(username: str, password: str) -> bool:
    user, pwd = credentials()
    return hmac.compare_digest(username, user) and hmac.compare_digest(password, pwd)


def valid_token(token: str) -> bool:
    user, _ = credentials()
    return bool(token) and hmac.compare_digest(token, make_token(user))
