"""Guard for outbound fetches of user-supplied URLs (SSRF defence).

Titan crawls whatever address a signup types in. Without a guard that is an
SSRF primitive: a stranger can point Titan at `http://169.254.169.254/`
(cloud metadata), at `http://127.0.0.1:7860/api/...` (its own private API,
from inside the trust boundary), or at a company's internal network — and get
the response back, rendered as an "audit".

It is also an abuse vector in the other direction. Titan fetching an arbitrary
host on demand, unmetered, means someone else's server gets hammered from
Titan's IP and Titan's reputation.

Three rules, in order:

1. **Scheme allowlist.** Only http and https. `file://`, `gopher://` and
   `ftp://` are all reachable through urllib otherwise, and `file:///etc/passwd`
   is a file read dressed as a crawl.
2. **Resolve, then check the ADDRESS — not the hostname.** Checking the string
   is the classic mistake: `evil.com` can resolve to `127.0.0.1`. Every
   resolved address must be public, and a hostname resolving to several
   addresses is rejected unless all of them are.
3. **Re-check on redirect.** A public URL that 302s to `169.254.169.254`
   defeats a check that only ran once, so redirects are followed manually with
   the same test applied at every hop.

This does not stop a determined attacker with DNS-rebinding timing, which needs
socket-level pinning. It stops the entire class of trivial abuse, and it says
so rather than implying more.
"""

from __future__ import annotations

import ipaddress
import socket
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

ALLOWED_SCHEMES = ("http", "https")
MAX_REDIRECTS = 4
MAX_BYTES = 1_500_000

# Hostnames that are never legitimate crawl targets, checked before DNS so a
# resolver that returns something public for them cannot help.
BLOCKED_HOSTNAMES = frozenset({
    "localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback",
    # AWS/GCP/Azure instance metadata. The single most valuable SSRF target.
    "metadata", "metadata.google.internal", "instance-data",
})


class BlockedURL(ValueError):
    """The URL is not a legitimate public crawl target."""


def _is_public(addr: str) -> bool:
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False
    # is_global is False for private, loopback, link-local, multicast,
    # reserved and unspecified ranges — including 169.254.169.254 and ::1.
    if not ip.is_global:
        return False
    # IPv4-mapped IPv6 (::ffff:127.0.0.1) reports as global on some versions;
    # unwrap and re-test rather than trust it.
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        return ip.ipv4_mapped.is_global
    return True


def check(url: str) -> str:
    """Validate one URL. Returns the normalised URL or raises BlockedURL."""
    if not url or not isinstance(url, str):
        raise BlockedURL("No URL given.")
    parsed = urllib.parse.urlparse(url.strip())

    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        raise BlockedURL(
            f"Only http and https can be audited — {parsed.scheme or 'that'} "
            f"is not a web address Titan will fetch.")

    host = (parsed.hostname or "").lower().rstrip(".")
    if not host:
        raise BlockedURL("That address has no hostname.")
    if host in BLOCKED_HOSTNAMES:
        raise BlockedURL(f"{host} is not a public website.")

    try:
        infos = socket.getaddrinfo(host, parsed.port or
                                   (443 if parsed.scheme == "https" else 80),
                                   proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise BlockedURL(f"{host} does not resolve — check the address.")

    addrs = {i[4][0] for i in infos}
    if not addrs:
        raise BlockedURL(f"{host} does not resolve to any address.")
    # ALL resolved addresses must be public. A host that returns one public and
    # one private address is a rebinding attempt, not a website.
    bad = [a for a in addrs if not _is_public(a)]
    if bad:
        raise BlockedURL(
            f"{host} resolves to a private or reserved address "
            f"({bad[0]}). Titan only audits sites on the public internet.")
    return url.strip()


def fetch(url: str, *, user_agent: str, timeout: float,
          max_bytes: int = MAX_BYTES) -> tuple[Optional[str], Optional[str], int]:
    """Fetch a user-supplied URL safely. Returns (html, error, status).

    Redirects are followed manually so every hop is re-validated — the whole
    point of the guard is lost if a public URL can bounce to a private one.
    """
    seen = 0
    current = url
    while True:
        try:
            current = check(current)
        except BlockedURL as e:
            return None, str(e), 0

        req = urllib.request.Request(current, headers={
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml",
        })
        try:
            # Redirects are NOT followed automatically — see class docstring.
            opener = urllib.request.build_opener(_NoRedirect)
            with opener.open(req, timeout=timeout) as r:
                raw = r.read(max_bytes)
                enc = r.headers.get_content_charset() or "utf-8"
                return raw.decode(enc, errors="replace"), None, r.status
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 303, 307, 308):
                target = e.headers.get("Location", "")
                if not target:
                    return None, f"HTTP {e.code} with no destination", e.code
                seen += 1
                if seen > MAX_REDIRECTS:
                    return None, "Too many redirects", e.code
                current = urllib.parse.urljoin(current, target)
                continue
            return None, f"HTTP {e.code}", e.code
        except Exception as e:
            return None, f"{type(e).__name__}", 0


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Surface redirects as HTTPError so each hop can be re-validated."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None
