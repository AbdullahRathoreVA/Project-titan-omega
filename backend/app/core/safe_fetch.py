"""SSRF protection for fetching user-supplied URLs.

Titan crawls whatever address a user types in. Without a guard, someone
could point it at cloud metadata (http://169.254.169.254/), at Titan's own
internal API (http://127.0.0.1:7860/...), or at a private network, and get
the response back as an "audit".

1. Only http and https. file://, gopher:// and ftp:// are refused.
2. Resolve the host and check the address, not the name - evil.com can
   resolve to 127.0.0.1. Every resolved address must be public.
3. Follow redirects manually and re-check each hop, since a public URL can
   redirect to a private one.

This doesn't stop DNS rebinding with precise timing (that needs pinning at
the socket level), but it covers the common cases.
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

# Hostnames that are never valid crawl targets, checked before DNS.
BLOCKED_HOSTNAMES = frozenset({
    "localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback",
    # Cloud instance metadata (AWS/GCP/Azure).
    "metadata", "metadata.google.internal", "instance-data",
})


class BlockedURL(ValueError):
    """The URL isn't a valid public crawl target."""


def _is_public(addr: str) -> bool:
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False
    # is_global is False for private, loopback, link-local, multicast, reserved
    # and unspecified ranges, including 169.254.169.254 and ::1.
    if not ip.is_global:
        return False
    # IPv4-mapped IPv6 (::ffff:127.0.0.1) reports as global on some Python
    # versions, so unwrap it and test again.
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
    # Every resolved address must be public. A host returning one public and one
    # private address is treated as a rebinding attempt.
    bad = [a for a in addrs if not _is_public(a)]
    if bad:
        raise BlockedURL(
            f"{host} resolves to a private or reserved address "
            f"({bad[0]}). Titan only audits sites on the public internet.")
    return url.strip()


def fetch(url: str, *, user_agent: str, timeout: float,
          max_bytes: int = MAX_BYTES) -> tuple[Optional[str], Optional[str], int]:
    """Fetch a user-supplied URL safely. Returns (html, error, status).

    Redirects are followed manually so each hop is validated.
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
            # Redirects aren't followed automatically; see fetch().
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
