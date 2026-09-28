"""Find a customer from anything you remember about them.

Typical case: someone emails about `example.com` and you want the account
behind it in one step.

- Founder only. This searches across tenants by design, which is what makes
  it useful to the operator and unsafe for a customer. It lives under
  ``/api/founder`` (already in ``demo_data._SENSITIVE_PREFIXES``). A
  per-tenant search should be a separate function with an org filter, not a
  flag on this one.
- Domains are matched on the host: ``https://example.com/``, ``example.com``
  and ``www.example.com`` are the same business.
- Every result says what it matched on, so a domain match can be told apart
  from a name coincidence.
- Nothing here reads a secret. Results come from the public accessors
  (`identity` never exposes a hash; `clients.public` is an allow-list), so a
  new private field can't leak through search.
"""

from __future__ import annotations

import re
from typing import Optional

ORG = "organisation"
USER = "person"
BUSINESS = "business"
ACCOUNT = "account"

_SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*://", re.I)


def normalise_host(value: str) -> str:
    """`https://WWW.Example.com/path` -> `example.com`.

    Not urlparse alone: many stored values are bare hostnames typed by a
    person, which urlparse reads as a path.
    """
    text = (value or "").strip().lower()
    if not text:
        return ""
    text = _SCHEME.sub("", text)
    text = text.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    text = text.split("@")[-1].split(":")[0]
    if text.startswith("www."):
        text = text[4:]
    return text


def _hit(kind: str, ident: str, label: str, sublabel: str, matched_on: str,
         extra: Optional[dict] = None) -> dict:
    rec = {"kind": kind, "id": ident, "label": label, "sublabel": sublabel,
           "matched_on": matched_on}
    if extra:
        rec.update(extra)
    return rec


def _contains(needle: str, *fields) -> Optional[str]:
    """Which field matched, or None. Returns the field name so the result can
    explain itself.
    """
    for name, value in fields:
        if value and needle in str(value).lower():
            return name
    return None


def search(query: str, limit: int = 20) -> dict:
    """Search organisations, people, businesses and billing accounts.

    If one source is unavailable the others still answer, and the payload
    names the source that couldn't be searched.
    """
    raw = (query or "").strip()
    needle = raw.lower()
    if len(needle) < 2:
        return {"query": raw, "results": [], "counts": {}, "searched": [],
                "unavailable": [],
                "note": "Enter at least two characters."}

    host = normalise_host(raw)
    results: list[dict] = []
    searched: list[str] = []
    unavailable: list[dict] = []

    # --- organisations ----------------------------------------------------
    try:
        from . import orgs
        for org in orgs.all_orgs():
            field = _contains(needle, ("name", org["name"]),
                              ("slug", org["slug"]), ("id", org["id"]))
            if field:
                results.append(_hit(ORG, org["id"], org["name"],
                                    f"{org['status']} · {org['slug']}", field))
        searched.append("organisations")
    except Exception as exc:                                   # noqa: BLE001
        unavailable.append({"source": "organisations", "error": str(exc)[:120]})

    # --- people -----------------------------------------------------------
    try:
        from . import identity
        for user in identity.all_users():
            field = _contains(needle, ("email", user["email"]),
                              ("id", user["id"]))
            if field:
                results.append(_hit(USER, user["id"], user["email"],
                                    f"{user['role']} · {user['status']}",
                                    field))
        searched.append("people")
    except Exception as exc:                                   # noqa: BLE001
        unavailable.append({"source": "people", "error": str(exc)[:120]})

    # --- businesses, including by domain ----------------------------------
    try:
        from . import clients as registry
        for row in registry.all_clients():
            rec = registry.public(row["id"]) or {}
            site = rec.get("website", "")
            field = _contains(needle, ("business_name", rec.get("business_name")),
                              ("website", site), ("id", rec.get("id")))
            # The main use case: paste a domain, find the business.
            if not field and host and normalise_host(site) == host:
                field = "domain"
            if field:
                results.append(_hit(
                    BUSINESS, rec.get("id", ""), rec.get("business_name", ""),
                    normalise_host(site) or rec.get("industry", ""), field,
                    {"website": site}))
        searched.append("businesses")
    except Exception as exc:                                   # noqa: BLE001
        unavailable.append({"source": "businesses", "error": str(exc)[:120]})

    # --- billing accounts -------------------------------------------------
    try:
        from . import analytics
        for account in analytics.accounts_snapshot()["accounts"]:
            field = _contains(needle, ("email", account["email"]),
                              ("plan", account["plan"]))
            if not field and host:
                for business in account.get("businesses", []):
                    if normalise_host(business.get("website", "")) == host:
                        field = "domain"
                        break
            if field:
                results.append(_hit(
                    ACCOUNT, account["email"], account["email"],
                    f"{account['plan_name']} · "
                    f"{'paying' if account['paying'] else 'not paying'}",
                    field,
                    {"granted": account.get("granted", False)}))
        searched.append("accounts")
    except Exception as exc:                                   # noqa: BLE001
        unavailable.append({"source": "accounts", "error": str(exc)[:120]})

    counts: dict[str, int] = {}
    for hit in results:
        counts[hit["kind"]] = counts.get(hit["kind"], 0) + 1

    # A domain match is almost always what the operator wants, so it sorts first;
    # everything else keeps its source order.
    results.sort(key=lambda r: 0 if r["matched_on"] == "domain" else 1)

    return {
        "query": raw,
        "host": host,
        "results": results[:max(1, min(int(limit or 20), 100))],
        "counts": counts,
        "total": len(results),
        "searched": searched,
        # Named rather than swallowed: fewer results because a source was down is
        # different from fewer results.
        "unavailable": unavailable,
    }
