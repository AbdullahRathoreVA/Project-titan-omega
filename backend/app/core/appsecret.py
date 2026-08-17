"""The one door to the deployment secret.

Before this module, ``TITAN_SECRET`` had **four different fallbacks in four
files**:

===================  ==========================================================
``auth.py``          ``"titan-omega-change-me"``
``sessions.py``      ``"titan-omega-change-me"``
``clients.py``       ``TITAN_TOKEN``, then ``"titan-dev-secret"`` — a different one
``site_access.py``   ``"titan-omega-change-me"`` — the WordPress credential vault
===================  ==========================================================

Every one of those strings is in the public git history. On a deployment with
``TITAN_SECRET`` unset that means session tokens — founder ones included — are
signed with a key anybody can read on GitHub and therefore mint for themselves,
and the credential vault is encrypted with a key derived from a published
constant. The vault is the worst of the four: it holds *other people's* site
credentials.

Two rules:

1. **A secret that is printed in the repository is not a secret.** Setting
   ``TITAN_SECRET`` to one of the historical fallbacks counts as unconfigured,
   because it is exactly as public as leaving it unset.
2. **Production refuses to invent one.** Where authentication is enforced, a
   missing secret raises at startup and the app serves nothing. Silently
   falling back is how a deployment ends up signing real sessions with a
   published key and nobody finds out.

Local development is unaffected: authentication is off there, so a clearly
labelled development secret is used and the dashboard still opens with no
friction.

Measured before this was written (2026-08-17): a guest token issued by the live
Space does not verify against any published default, so ``TITAN_SECRET`` IS set
in production and making it mandatory does not take the site down. That was
checked rather than assumed, because the failure mode of assuming wrong is a
dead product.
"""

from __future__ import annotations

import os

# Every string that has ever been a fallback in this repository. All of them are
# readable in the git history, so a deployment using one is not configured.
PUBLISHED_DEFAULTS = frozenset({
    "titan-omega-change-me",
    "titan-dev-secret",
    "titan-dev",
    "change-me",
})

# Used ONLY where authentication is off. Named so that anyone finding it in a
# token dump knows immediately what they are looking at.
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
    secret."""
    if configured():
        return raw()
    if enforced():
        raise MissingSecret(_MESSAGE)
    return DEV_SECRET


def key() -> bytes:
    return value().encode()


def status() -> dict:
    """Founder-visible state. Reports *whether* there is a secret, never what
    it is — a status endpoint that leaks the key it is describing would be a
    remarkable own goal."""
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
