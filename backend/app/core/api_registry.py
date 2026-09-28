"""What external APIs exist, and which provider to reach for.

Built from the public-apis catalogue (1,675 APIs, 52 categories), parsed by
`evaluation/sync_public_apis.py` and committed as JSON so the app never needs
GitHub to answer "what APIs exist".

Every record here is catalogue metadata: an API was listed upstream with this
name, URL, category and auth type. It says nothing about whether Titan can
call it. An adapter needs the provider's docs read, auth wired, schema mapped
and responses normalised, and that's per-provider work.

So every record starts as `METADATA_ONLY` and nothing promotes itself; a
provider reaches `ADAPTER_READY` only when someone writes and tests an
adapter. Even so, Titan can answer "which providers serve weather, need no
credential and support HTTPS" from real data, which is the hard half of
routing.

Nothing here makes a network call. Calling a provider goes through the
hardened path (`safe_fetch` for SSRF, `ratelimit`, `untrusted` for
responses) and isn't wired up here: a registry that could also fire requests
would be one prompt injection away from an SSRF engine with 1,675 targets.
"""

from __future__ import annotations

import json
import os
import re
import threading
from typing import Optional

# Status values, weakest to strongest.
METADATA_ONLY = "METADATA_ONLY"
AUTH_REQUIRED = "AUTH_REQUIRED"
ADAPTER_READY = "ADAPTER_READY"
FULLY_INTEGRATED = "FULLY_INTEGRATED"
UNAVAILABLE = "UNAVAILABLE"
BLOCKED = "BLOCKED"
NEEDS_MANUAL_REVIEW = "NEEDS_MANUAL_REVIEW"

_DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "..", "data", "public_apis.json")

_lock = threading.RLock()
_apis: list[dict] = []
_meta: dict = {}

# Intent words -> upstream category names. The catalogue's categories are the
# capability graph; this maps natural language onto them without inventing a
# separate taxonomy.
_INTENT: dict[str, tuple] = {
    "weather": ("Weather",),
    "forecast": ("Weather",),
    "currency": ("Currency Exchange", "Finance"),
    "exchange rate": ("Currency Exchange",),
    "stock": ("Finance",),
    "crypto": ("Cryptocurrency",),
    "bitcoin": ("Cryptocurrency",),
    "geocode": ("Geocoding",),
    "location": ("Geocoding",),
    "address": ("Geocoding",),
    "news": ("News",),
    "email": ("Email",),
    "phone": ("Phone",),
    "job": ("Jobs",),
    "company": ("Business",),
    "business": ("Business",),
    "government": ("Government",),
    "health": ("Health",),
    "science": ("Science & Math",),
    "book": ("Books",),
    "music": ("Music",),
    "video": ("Video",),
    "photo": ("Photography",),
    "image": ("Photography",),
    "sport": ("Sports & Fitness",),
    "food": ("Food & Drink",),
    "transport": ("Transportation",),
    "vehicle": ("Vehicle",),
    "security": ("Security",),
    "malware": ("Anti-Malware",),
    "translate": ("Text Analysis",),
    "text": ("Text Analysis",),
    "machine learning": ("Machine Learning",),
    "url shorten": ("URL Shorteners",),
    "test data": ("Test Data",),
    "calendar": ("Calendar",),
    "shopping": ("Shopping",),
    "social": ("Social",),
    "open data": ("Open Data",),
    "development": ("Development",),
}


def load(force: bool = False) -> dict:
    """Load the catalogue from disk. Never raises, never fetches."""
    global _apis, _meta
    with _lock:
        if _apis and not force:
            return {"ok": True, "count": len(_apis), "cached": True}
        try:
            with open(os.path.normpath(_DATA), encoding="utf-8") as f:
                payload = json.load(f)
        except Exception as e:
            _apis, _meta = [], {}
            return {"ok": False, "count": 0,
                    "error": (f"The API catalogue is not available "
                              f"({type(e).__name__}). Run "
                              f"`python -m evaluation.sync_public_apis`.")}
        rows = payload.get("apis") or []
        for i, r in enumerate(rows):
            r.setdefault("id", f"pa-{i:05d}")
            # Set here, not in the data file, so it can never be committed as anything
            # stronger by accident.
            r["status"] = METADATA_ONLY
            r["adapter"] = None
        _apis = rows
        _meta = {k: v for k, v in payload.items() if k != "apis"}
        return {"ok": True, "count": len(_apis), "cached": False}


def all_apis() -> list[dict]:
    load()
    with _lock:
        return list(_apis)


def categories() -> list[dict]:
    load()
    counts: dict[str, int] = {}
    with _lock:
        for r in _apis:
            counts[r["category"]] = counts.get(r["category"], 0) + 1
    return [{"category": c, "apis": n}
            for c, n in sorted(counts.items(), key=lambda x: -x[1])]


def search(query: str = "", *, category: str = "", auth: str = "",
           no_credential: bool = False, https_only: bool = False,
           limit: int = 25) -> dict:
    """Find providers. Metadata filtering only - no network, no execution."""
    load()
    q = (query or "").strip().lower()
    with _lock:
        rows = list(_apis)

    if category:
        rows = [r for r in rows if r["category"].lower() == category.lower()]
    if auth:
        rows = [r for r in rows if r["auth"] == auth.lower()]
    if no_credential:
        rows = [r for r in rows if r["auth"] == "none"]
    if https_only:
        # `is True` on purpose: unknown mustn't pass an HTTPS-only filter.
        rows = [r for r in rows if r["https"] is True]

    scored = []
    if q:
        words = [w for w in re.split(r"\W+", q) if len(w) > 1]
        for r in rows:
            hay = f"{r['name']} {r['description']} {r['category']}".lower()
            hits = sum(1 for w in words if w in hay)
            if not hits:
                continue
            # Name matches beat description matches.
            score = hits + (2 if q in r["name"].lower() else 0)
            scored.append((score, r))
        scored.sort(key=lambda s: -s[0])
        rows = [r for _s, r in scored]

    return {"total": len(rows), "results": rows[:max(1, limit)],
            "query": query, "filters": {
                "category": category or None, "auth": auth or None,
                "no_credential": no_credential, "https_only": https_only}}


def for_capability(intent: str, *, prefer_free: bool = True,
                   limit: int = 5) -> dict:
    """Map an intent onto candidate providers, best first.

    The ranking uses catalogue facts (credential needed, HTTPS, CORS), not an
    unmeasured quality score.

    Returns candidates, not a connection. Every one is METADATA_ONLY, so the
    output is "here's who serves this and what they'd need", not an answer.
    """
    load()
    text = (intent or "").strip().lower()
    matched = [cats for key, cats in _INTENT.items() if key in text]
    cats = sorted({c for group in matched for c in group})

    if cats:
        rows = [r for r in all_apis() if r["category"] in cats]
    else:
        rows = search(text, limit=200)["results"]

    def rank(r: dict) -> tuple:
        # No credential first (Titan runs on no budget), then HTTPS, then a known CORS
        # answer. Every term is a catalogue fact.
        return (
            0 if r["auth"] == "none" else 1,
            0 if r["https"] is True else 1,
            0 if r["cors"] is True else 1,
            r["name"].lower(),
        )

    if prefer_free:
        rows = sorted(rows, key=rank)

    return {
        "intent": intent,
        "capabilities": cats or ["(no category matched — full-text search)"],
        "candidates": rows[:max(1, limit)],
        "total_candidates": len(rows),
        "note": (
            "Candidates are CATALOGUE ENTRIES, not connections. Every provider "
            "here is METADATA_ONLY: Titan knows it exists, what category it "
            "serves and whether it needs a credential, and has NOT integrated "
            "it. Calling one requires an adapter written against that "
            "provider's own documentation."),
    }


def stats() -> dict:
    """Integration counts: catalogued vs actually integrated."""
    load()
    with _lock:
        rows = list(_apis)
        meta = dict(_meta)
    by_status: dict[str, int] = {}
    by_auth: dict[str, int] = {}
    for r in rows:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
        by_auth[r["auth"]] = by_auth.get(r["auth"], 0) + 1
    return {
        "total": len(rows),
        "categories": len(categories()),
        "by_status": by_status,
        "by_auth": by_auth,
        "no_credential_required": by_auth.get("none", 0),
        "https_confirmed": sum(1 for r in rows if r["https"] is True),
        "https_unknown": sum(1 for r in rows if r["https"] is None),
        "adapters_written": sum(1 for r in rows if r.get("adapter")),
        "source": meta.get("source"),
        "synced_at": meta.get("synced_at"),
        "note": (
            "Every entry is METADATA_ONLY. Titan has catalogued these "
            "providers; it has not integrated them. `adapters_written` is the "
            "only number here that would mean Titan can actually call "
            "something, and it is 0 — writing an adapter means reading a "
            "provider's own docs, wiring its auth, mapping its schema and "
            "testing it. Health checks are deliberately not run: probing "
            "1,675 third-party endpoints on a schedule is abusive traffic, "
            "not diligence."),
    }


def reset() -> None:
    """Test seam."""
    global _apis, _meta
    with _lock:
        _apis, _meta = [], {}
