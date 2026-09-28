"""Access to the deployment secret (TITAN_SECRET).

It signs session tokens and derives the key for the credential vault, which
holds customers' site credentials. Two rules:

1. A value that appears in the repository isn't a secret. Every string that
   was ever a fallback here is in the public git history, so setting
   ``TITAN_SECRET`` to one of them counts as unconfigured.
2. Production won't invent one. Where authentication is enforced, a missing
   secret raises at startup and the app serves nothing, rather than quietly
   signing real sessions with a published key.

Local development is unaffected: authentication is off there, so a clearly
labelled development secret is used.
"""

from __future__ import annotations

import os

# Every string that has ever been a fallback in this repository. All are
# readable in the git history, so a deployment using one isn't configured.
PUBLISHED_DEFAULTS = frozenset({
    "titan-omega-change-me",
    "titan-dev-secret",
    "titan-dev",
    "change-me",
})

# Used only where authentication is off. Named so anyone who finds it in a
# token dump knows what it is.
DEV_SECRET = "titan-local-development-only-not-a-production-secret"

_MESSAGE = (
    "TITAN_SECRET is not set (or is set to a value published in this "
    "repository), and this deployment enforces authentication. Refusing to "
    "start: signing sessions and encrypting stored site credentials with a key "
    "that anyone can read from the source is worse than being down. Set "
    "TITAN_SECRET to a long random string on the host — e.g. "
    "`python -c \"import secrets; print(secrets.token_urlsafe(48))\"` — and "
    "restart. Rotating it signs everyone out once, which is expected."
)


class MissingSecret(RuntimeError):
    """Raised at startup when a production deployment has no usable secret."""


def raw() -> str:
    return os.getenv("TITAN_SECRET", "").strip()


def configured() -> bool:
    """Is there a secret, and is it actually secret?"""
    value_ = raw()
    return bool(value_) and value_ not in PUBLISHED_DEFAULTS


def enforced() -> bool:
    """Production is any deployment that enforces authentication."""
    return os.getenv("TITAN_REQUIRE_AUTH") == "1"


def value() -> str:
    """The secret, or a labelled development one. Never an invented production
    secret.
    """
    if configured():
        return raw()
    if enforced():
        raise MissingSecret(_MESSAGE)
    return DEV_SECRET


def key() -> bytes:
    return value().encode()


def status() -> dict:
    """Founder-visible state. Reports whether there is a secret, never what it
    is.
    """
    current = raw()
    return {
        "configured": configured(),
        "enforced": enforced(),
        "using_published_default": bool(current) and current in PUBLISHED_DEFAULTS,
        "source": ("TITAN_SECRET" if configured()
                   else "none" if enforced()
                   else "development fallback"),
    }


def verify_at_startup() -> None:
    """Called from the app lifespan.

    A deployment that enforces authentication and has no usable secret must not
    serve a single request.
    """
    if enforced() and not configured():
        raise MissingSecret(_MESSAGE)
