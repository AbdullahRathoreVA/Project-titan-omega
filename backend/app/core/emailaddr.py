"""Is this an address a person could actually receive mail at?

Junk addresses (`xx@xx`, `@@@@@`) inflate the signup funnel, can never be
emailed, and can't be told apart from a typo in a real address.

Two separate checks:

`valid_syntax()` is a shape check: free, deterministic, always on. It answers
"could this be an address at all".

`deliverable()` asks DNS whether the domain has a mail exchanger. That's the
only way to tell a real address from a well-formed invented one without
sending anything, and it needs no provider or cost. It's off by default and
fails open: a DNS timeout, resolver outage or any error returns "unknown",
never "invalid". Turning away a paying customer because a nameserver blinked
is worse than accepting one bad address.

Neither proves the mailbox exists. Only a delivered message does, and sending
needs an email provider Titan doesn't have yet, so `verified` is never set to
true here.
"""

from __future__ import annotations

import os
import re
from typing import Optional

# Not a full RFC 5322 regex: that grammar allows addresses no mail system
# accepts, and a pattern claiming full compliance suggests anything it passes
# is deliverable. This is the practical shape: a local part, one @, a dotted
# domain.
_LOCAL = r"[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*"
_LABEL = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
_PATTERN = re.compile(rf"^{_LOCAL}@(?:{_LABEL}\.)+[A-Za-z]{{2,63}}$")

MAX_LENGTH = 254          # RFC 5321 limit on the whole address
MAX_LOCAL = 64            # RFC 5321 limit on the part before the @

# Reserved by RFC 2606 and RFC 6761; these can never receive mail. They're
# still accepted, because tests and docs use example.com and the validator must
# behave the same in tests and production. `reserved()` reports them so a
# caller can exclude them deliberately.
RESERVED_TLDS = frozenset({
    "test", "example", "invalid", "localhost", "local", "onion",
})
RESERVED_DOMAINS = frozenset({
    "example.com", "example.org", "example.net",
})


def normalise(email: str) -> str:
    """Trim and lower-case. The local part is technically case-sensitive, but no
    mainstream provider treats it that way, and two accounts differing only
    in case would just cause confusion.
    """
    return (email or "").strip().lower()


def valid_syntax(email: str) -> bool:
    """Could this be an address at all? Free, deterministic, always on."""
    addr = normalise(email)
    if not addr or len(addr) > MAX_LENGTH:
        return False
    if addr.count("@") != 1:
        return False
    local, _, domain = addr.partition("@")
    if not local or len(local) > MAX_LOCAL:
        return False
    if ".." in local or ".." in domain:
        return False
    if domain.startswith("-") or domain.endswith("-"):
        return False
    return bool(_PATTERN.match(addr))


def domain_of(email: str) -> str:
    return normalise(email).partition("@")[2]


def reserved(email: str) -> bool:
    """A documentation or reserved address that can never receive mail."""
    domain = domain_of(email)
    if not domain:
        return False
    return domain in RESERVED_DOMAINS or domain.rsplit(".", 1)[-1] in RESERVED_TLDS


def mx_checking_enabled() -> bool:
    """Off by default. A network call on the signup path should be opted into,
    and only where DNS is reliable.
    """
    return os.getenv("TITAN_VERIFY_EMAIL_MX", "0") == "1"


def deliverable(email: str, timeout: float = 3.0) -> dict:
    """Can this domain receive mail? Never raises. Fails open.

    Returns {"checked", "deliverable", "reason"}. `deliverable` is None when
    the answer is unknown, which covers every failure mode: check disabled, no
    resolver, a timeout, a malformed response. Only a definitive "no mail
    exchanger and no address record" returns False.

    Callers never treat unknown as invalid.
    """
    domain = domain_of(email)
    if not domain:
        return {"checked": False, "deliverable": None,
                "reason": "no domain in the address"}
    if not mx_checking_enabled():
        return {"checked": False, "deliverable": None,
                "reason": "MX checking is off (set TITAN_VERIFY_EMAIL_MX=1)"}
    try:
        # Imported inside the function: a resolver is optional, and a missing one
        # should give "unknown" rather than break importing billing.
        import dns.resolver  # type: ignore
    except Exception:
        return {"checked": False, "deliverable": None,
                "reason": "no DNS resolver library installed"}
    try:
        resolver = dns.resolver.Resolver()
        resolver.lifetime = timeout
        resolver.timeout = timeout
        answers = resolver.resolve(domain, "MX")
        if len(answers):
            return {"checked": True, "deliverable": True,
                    "reason": f"{len(answers)} mail exchanger(s)"}
    except Exception as exc:                                   # noqa: BLE001
        name = type(exc).__name__
        # NXDOMAIN and NoAnswer are real answers. Everything else (timeouts, resolver
        # errors, no nameservers) is a failure on our side, not theirs.
        if name in ("NXDOMAIN", "NoAnswer"):
            try:
                resolver.resolve(domain, "A")
                # An A record with no MX still accepts mail under RFC 5321 §5.1.
                return {"checked": True, "deliverable": True,
                        "reason": "no MX, but an address record accepts mail"}
            except Exception:
                return {"checked": True, "deliverable": False,
                        "reason": "the domain has no mail exchanger"}
        return {"checked": False, "deliverable": None,
                "reason": f"lookup failed: {name}"}
    return {"checked": True, "deliverable": False,
            "reason": "the domain has no mail exchanger"}


def check(email: str) -> dict:
    """Everything known about an address, without sending anything.

    `verified` is always False: only a delivered message proves a mailbox
    exists, and sending needs a provider Titan doesn't have yet.
    """
    addr = normalise(email)
    ok = valid_syntax(addr)
    return {
        "email": addr,
        "valid_syntax": ok,
        "reserved": reserved(addr) if ok else False,
        "deliverable": deliverable(addr) if ok else {
            "checked": False, "deliverable": None,
            "reason": "the address is not a valid shape"},
        "verified": False,
        "verified_note": ("Nothing here proves the mailbox exists. Only a "
                          "delivered message does, and that needs an email "
                          "provider Titan is not configured with."),
    }


def reason_invalid(email: str) -> Optional[str]:
    """Why this address was refused, in words a person can act on, or None."""
    addr = normalise(email)
    if not addr:
        return "An email address is required."
    if "@" not in addr:
        return "That is not an email address — it needs an @."
    if addr.count("@") > 1:
        return "An email address has one @."
    local, _, domain = addr.partition("@")
    if not local:
        return "There is nothing before the @."
    if not domain:
        return "There is nothing after the @."
    if "." not in domain:
        return (f"'{domain}' is not a full domain — it needs a dot, "
                f"like {domain}.com.")
    if len(addr) > MAX_LENGTH:
        return "That address is too long to be delivered to."
    if not valid_syntax(addr):
        return "That does not look like an address mail could be delivered to."
    return None
