"""Encrypted storage for a client's website credentials.

Once Titan starts fixing sites rather than just auditing them, it holds a key
to someone else's business, so the rules here are stricter:

* Encrypted at rest. A credential is never written in plaintext. The key comes
  from ``TITAN_CREDENTIAL_KEY`` (or is derived from ``TITAN_SECRET``), so a
  leaked state file isn't a leaked password.
* Never returned. No endpoint, log line, error or debug payload emits the
  secret, not even to the founder. Once stored it can be used, tested and
  deleted, but not read.
* WordPress Application Passwords, not the real password. WordPress has had
  these since 5.6 for exactly this: a scoped credential the owner can revoke
  from their profile without changing their login.
* Revocable from both ends: the client revokes it in WordPress, or the
  founder disconnects here. Either is enough to end access.

Connecting proves Titan can write and reports what it would be allowed to do.
Applying a fix is a separate, approved action; nothing is changed
automatically.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import threading
import time
from typing import Optional

PROVIDERS = ("wordpress",)

_lock = threading.RLock()
# client_id -> {provider, site_url, username, secret (encrypted), added_at, ...}
_store: dict[str, dict] = {}


def _key() -> bytes:
    """A 32-byte urlsafe-base64 key for Fernet.

    Derived from TITAN_SECRET when no dedicated key is set, so it works out of
    the box. A dedicated TITAN_CREDENTIAL_KEY means rotating the session secret
    doesn't lock every client's site out.
    """
    raw = os.getenv("TITAN_CREDENTIAL_KEY", "").strip()
    if raw:
        try:
            if len(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))) == 32:
                return raw.encode()
        except Exception:
            pass
        return base64.urlsafe_b64encode(hashlib.sha256(raw.encode()).digest())
    # Goes through appsecret so a deployment without TITAN_SECRET never derives
    # the vault key from a published default. The derivation itself is unchanged,
    # so existing stored credentials still decrypt.
    from . import appsecret
    seed = appsecret.value()
    return base64.urlsafe_b64encode(hashlib.sha256(
        ("credential:" + seed).encode()).digest())


def encryption_available() -> bool:
    try:
        import cryptography  # noqa: F401
        return True
    except Exception:
        return False


def _encrypt(secret: str) -> Optional[str]:
    """Encrypt, or None if it can't be done safely.

    Returning None rather than falling back to plaintext is deliberate: a
    connection that refuses and says why beats a credential stored in the
    clear because a package was missing.
    """
    try:
        from cryptography.fernet import Fernet
        return Fernet(_key()).encrypt(secret.encode()).decode()
    except Exception:
        return None


def _decrypt(blob: str) -> Optional[str]:
    try:
        from cryptography.fernet import Fernet
        return Fernet(_key()).decrypt(blob.encode()).decode()
    except Exception:
        return None


def setup_guide(provider: str = "wordpress") -> dict:
    """Step-by-step instructions for a non-technical owner to create the credential.

    Written for the client, not a developer: the steps name what they'll
    actually see on screen.
    """
    if provider != "wordpress":
        return {"provider": provider, "supported": False,
                "note": f"Titan can only connect to WordPress so far, not {provider}."}
    return {
        "provider": "wordpress",
        "supported": True,
        "needs": ["site_url", "username", "application_password"],
        "why_not_your_password": (
            "Titan never asks for your real WordPress password. An application "
            "password is a separate key you can cancel at any time without "
            "changing your login, and it can be revoked the second you want "
            "Titan to stop."),
        # The step that usually blocks people: the site was built by someone else and
        # the owner only has the hosting login. That's not a dead end - every major
        # host can open wp-admin without the WordPress password.
        "if_you_cannot_sign_in_to_wordpress": {
            "note": (
                "You do not need the WordPress password. If you can reach the "
                "hosting account, you can open the WordPress admin from it and "
                "create the key from there."),
            "hosts": [
                {
                    "host": "Hostinger",
                    "steps": [
                        "Sign in at hpanel.hostinger.com.",
                        "Sidebar -> Websites -> Websites list.",
                        "Click 'WP Admin' (older accounts call it 'Admin "
                        "Panel') next to the site.",
                        "That opens the WordPress admin already signed in - no "
                        "WordPress password needed.",
                        "Now follow the steps below from 'Users'.",
                    ],
                },
                {
                    "host": "cPanel (most shared hosting)",
                    "steps": [
                        "Sign in to cPanel.",
                        "Open 'WordPress Manager by Softaculous' (or "
                        "'Softaculous Apps Installer' -> WordPress).",
                        "Find the site and use the 'Log in' / admin shortcut.",
                        "Now follow the steps below from 'Users'.",
                    ],
                },
                {
                    "host": "I do not know / somebody else built it",
                    "steps": [
                        "Ask whoever holds the hosting account to do the steps "
                        "below and send you only the generated key.",
                        "They never have to give you their password, and they "
                        "can cancel the key at any time.",
                        "If nobody has the hosting login either, use 'Lost your "
                        "password?' on yoursite.com/wp-login.php - the reset "
                        "email goes to the address WordPress has on file.",
                    ],
                },
            ],
        },
        "steps": [
            "Sign in to your WordPress admin (usually yoursite.com/wp-admin). "
            "If you cannot, see 'if_you_cannot_sign_in_to_wordpress' above - "
            "your hosting account can open it without the WordPress password.",
            "Hover 'Users' in the left menu and click 'Profile'.",
            "Scroll to the bottom, to the 'Application Passwords' section.",
            "In 'New Application Password Name' type: Titan Omega",
            "Click 'Add New Application Password'.",
            "WordPress shows a code like abcd EFGH ijkl MNOP qrst UVWX. Copy it "
            "now — it is shown once.",
            "Paste it here along with your site address and your WordPress "
            "username.",
        ],
        "requirements": [
            "WordPress 5.6 or newer (application passwords are built in).",
            "The site must be served over HTTPS — WordPress disables "
            "application passwords on plain HTTP.",
            "Your user needs the Editor or Administrator role for Titan to fix "
            "pages.",
        ],
        "to_revoke": (
            "Same screen: Users → Profile → Application Passwords → Revoke. "
            "Titan loses access immediately, and you do not need to tell us."),
        "what_titan_will_do": [
            "Read your pages to see what is actually published.",
            "Propose fixes: titles, meta descriptions, schema markup, image "
            "alt text, and the legal pages your country requires.",
            "Apply a fix only after it is approved. Nothing is changed on your "
            "site without that.",
        ],
    }


def connect(client_id: str, provider: str, site_url: str, username: str,
            secret: str) -> dict:
    """Store a credential after checking it works. Never stores plaintext."""
    if provider not in PROVIDERS:
        return {"ok": False, "error": f"Unsupported provider: {provider}."}
    site_url = (site_url or "").strip().rstrip("/")
    if not site_url.startswith("https://"):
        return {"ok": False, "error": (
            "The site address must start with https://. WordPress refuses "
            "application passwords over plain http, so a connection would "
            "fail on the first request.")}
    if not username or not secret:
        return {"ok": False, "error": "Username and application password are both required."}

    if not encryption_available():
        return {"ok": False, "error": (
            "Credential encryption is unavailable in this deployment "
            "(the cryptography package is missing), so Titan will not store a "
            "customer's website password. It is in requirements.txt — the "
            "Space needs a rebuild.")}

    probe = verify(provider, site_url, username, secret)
    if not probe["ok"]:
        return {"ok": False, "error": probe["error"], "probe": probe}

    blob = _encrypt(secret)
    if not blob:
        return {"ok": False, "error": "Could not encrypt the credential; nothing was stored."}

    with _lock:
        _store[client_id] = {
            "provider": provider,
            "site_url": site_url,
            "username": username,
            "secret": blob,
            "added_at": time.time(),
            "last_verified": time.time(),
            "capabilities": probe.get("capabilities", []),
            "wp_user": probe.get("user", ""),
        }
    return {"ok": True, "provider": provider, "site_url": site_url,
            "capabilities": probe.get("capabilities", []),
            "note": ("Connected. Titan can now read the site and propose "
                     "fixes. Nothing will be changed without approval.")}


def verify(provider: str, site_url: str, username: str,
           secret: str) -> dict:
    """Check a credential works, and report what it's allowed to do."""
    if provider != "wordpress":
        return {"ok": False, "error": f"Unsupported provider: {provider}."}
    try:
        import base64 as _b64
        import httpx
        from . import safe_fetch

        try:
            safe_fetch.check(site_url)
        except Exception as e:
            return {"ok": False, "error": str(e)}

        token = _b64.b64encode(f"{username}:{secret}".encode()).decode()
        with httpx.Client(timeout=20.0, follow_redirects=True) as c:
            r = c.get(f"{site_url}/wp-json/wp/v2/users/me?context=edit",
                      headers={"Authorization": f"Basic {token}"})
        if r.status_code == 401:
            return {"ok": False, "error": (
                "WordPress rejected those details. Check the username is your "
                "WordPress username (not your email) and that the application "
                "password was copied completely, including the spaces.")}
        if r.status_code == 404:
            return {"ok": False, "error": (
                "That address does not expose the WordPress REST API. It may "
                "not be a WordPress site, or a security plugin is blocking "
                "/wp-json.")}
        if r.status_code >= 400:
            return {"ok": False, "error": f"WordPress replied {r.status_code}."}

        data = r.json()
        caps = data.get("capabilities") or {}
        allowed = [c for c in ("edit_posts", "edit_pages", "edit_others_posts",
                               "manage_options", "upload_files") if caps.get(c)]
        if "edit_posts" not in allowed and "edit_pages" not in allowed:
            return {"ok": False, "error": (
                f"Connected as {data.get('name', username)}, but that user "
                f"cannot edit content. Titan needs the Editor or "
                f"Administrator role to fix anything.")}
        return {"ok": True, "user": data.get("name", username),
                "capabilities": allowed}
    except Exception as e:
        return {"ok": False, "error": f"Could not reach the site ({type(e).__name__})."}


def credential(client_id: str) -> Optional[dict]:
    """Decrypt for internal use only. Never expose the return value."""
    with _lock:
        rec = _store.get(client_id)
    if not rec:
        return None
    secret = _decrypt(rec["secret"])
    if not secret:
        return None
    return {"provider": rec["provider"], "site_url": rec["site_url"],
            "username": rec["username"], "secret": secret}


def status(client_id: str) -> dict:
    """Safe to send over the wire. Never includes the secret."""
    with _lock:
        rec = _store.get(client_id)
    if not rec:
        return {"connected": False,
                "note": "No website credential. Titan can audit but not fix."}
    return {
        "connected": True,
        "provider": rec["provider"],
        "site_url": rec["site_url"],
        "username": rec["username"],
        "capabilities": rec.get("capabilities", []),
        "added_at": rec["added_at"],
        "last_verified": rec.get("last_verified"),
        "note": ("Titan can read this site and propose fixes. Nothing is "
                 "applied without approval."),
    }


def connected_ids() -> list[str]:
    """Clients whose site Titan currently holds a key to.

    The 24/7 fix cycle uses this to know what it's responsible for. Ids only,
    never the record or the secret.
    """
    with _lock:
        return sorted(_store)


def disconnect(client_id: str) -> dict:
    with _lock:
        existed = _store.pop(client_id, None) is not None
    return {"disconnected": existed,
            "note": ("Also revoke it in WordPress (Users → Profile → "
                     "Application Passwords) so the key stops working "
                     "everywhere, not just here.")}


# ------------------------------------------------------------ persistence --
def export_state() -> dict:
    with _lock:
        return {"sites": {k: dict(v) for k, v in _store.items()}}


def import_state(data: dict) -> None:
    if not isinstance(data, dict):
        return
    rows = data.get("sites")
    if not isinstance(rows, dict):
        return
    with _lock:
        _store.clear()
        for cid, rec in rows.items():
            if isinstance(rec, dict) and rec.get("secret") and rec.get("site_url"):
                _store[cid] = rec


def reset() -> None:
    """Test seam."""
    with _lock:
        _store.clear()
