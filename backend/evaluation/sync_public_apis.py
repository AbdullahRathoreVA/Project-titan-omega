"""Parse the public-apis catalogue into Titan's API registry.

Source of truth: https://github.com/public-apis/public-apis (README.md).

This is the `titan api sync` step from the brief. It is a BUILD-TIME script,
not a runtime dependency: the parsed catalogue is committed as JSON so the
product never needs GitHub to be reachable to answer "what APIs exist".

Parses dynamically rather than hard-coding the category list, so a future
change to the upstream repository is picked up by re-running this.

Run:  python -m evaluation.sync_public_apis
      python -m evaluation.sync_public_apis --offline   (reuse cached README)
"""

from __future__ import annotations

import io
import json
import os
import re
import sys
import time
import urllib.request

README_URL = ("https://raw.githubusercontent.com/public-apis/public-apis/"
              "master/README.md")
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "app", "data", "public_apis.json")
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     ".public_apis_readme.md")

# A row is: | [Name](link) | Description | Auth | HTTPS | CORS |
_ROW = re.compile(
    r"^\|\s*\[([^\]]+)\]\(([^)]+)\)\s*\|([^|]*)\|([^|]*)\|([^|]*)\|([^|]*)\|",
    re.M)
_HEADING = re.compile(r"^###\s+(.+?)\s*$", re.M)


def fetch(offline: bool = False) -> str:
    if offline and os.path.exists(CACHE):
        return io.open(CACHE, encoding="utf-8").read()
    req = urllib.request.Request(README_URL, headers={"User-Agent": "titan-omega"})
    with urllib.request.urlopen(req, timeout=60) as r:
        text = r.read().decode("utf-8", "replace")
    io.open(CACHE, "w", encoding="utf-8", newline="").write(text)
    return text


def _clean(s: str) -> str:
    s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s or "")   # strip md links
    s = re.sub(r"<[^>]+>", "", s)                          # strip html
    s = s.replace("`", "")                                 # upstream wraps
    return re.sub(r"\s+", " ", s).strip()                  # auth in backticks


def _auth(raw: str) -> str:
    """Normalise the auth column into a small closed set.

    Upstream writes `apiKey`, `OAuth`, `No`, and a handful of one-offs like
    `X-Mashape-Key` and `User-Agent`. Left raw these fragment the registry —
    "apikey" and "`apikey`" would be two different auth types and a filter for
    "no credential needed" would miss half the free APIs.
    """
    v = _clean(raw).lower()
    if v in ("", "no", "none"):
        return "none"
    if "oauth" in v:
        return "oauth"
    if "apikey" in v or "api key" in v:
        return "apikey"
    if "bearer" in v or "token" in v:
        return "token"
    if "basic" in v:
        return "basic"
    if v == "documentation":
        # Upstream uses this where the auth scheme is only described in the
        # provider's docs. Unknown is the honest label, not "none".
        return "unknown"
    # X-Mashape-Key, User-Agent, and friends: a header-carried credential.
    return "header"


def _tri(v: str):
    """Yes / No / anything else. Unknown stays None, never False.

    The upstream table uses "Unknown" in real rows. Collapsing that to False
    would state as fact that an API lacks HTTPS or CORS when nobody checked.
    """
    v = _clean(v).lower()
    if v.startswith("yes"):
        return True
    if v.startswith("no"):
        return False
    return None


def parse(markdown: str) -> list[dict]:
    """Every row, tagged with the category heading it sits under."""
    # Walk headings and rows together so each row knows its section.
    marks = [(m.start(), "h", _clean(m.group(1))) for m in _HEADING.finditer(markdown)]
    marks += [(m.start(), "r", m) for m in _ROW.finditer(markdown)]
    marks.sort(key=lambda x: x[0])

    out, category = [], ""
    seen = set()
    for _pos, kind, payload in marks:
        if kind == "h":
            category = payload
            continue
        name = _clean(payload.group(1))
        url = (payload.group(2) or "").strip()
        # The header row of each table parses as a row; drop it.
        if not name or name.lower() in ("api", "name") or not url.startswith("http"):
            continue
        key = f"{name}|{url}".lower()
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "name": name,
            "url": url,
            "description": _clean(payload.group(3)),
            "category": category,
            "auth": _auth(payload.group(4)),
            "https": _tri(payload.group(5)),
            "cors": _tri(payload.group(6)),
        })
    return out


def main() -> int:
    offline = "--offline" in sys.argv
    markdown = fetch(offline)
    rows = parse(markdown)
    if len(rows) < 500:
        print(f"REFUSING to write: only {len(rows)} rows parsed. The upstream "
              f"table format probably changed — fix the parser rather than "
              f"shipping a truncated catalogue.")
        return 1

    cats: dict[str, int] = {}
    auths: dict[str, int] = {}
    for r in rows:
        cats[r["category"]] = cats.get(r["category"], 0) + 1
        auths[r["auth"]] = auths.get(r["auth"], 0) + 1

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    payload = {
        "source": "https://github.com/public-apis/public-apis",
        "synced_at": time.time(),
        "count": len(rows),
        "categories": len(cats),
        "apis": rows,
    }
    io.open(OUT, "w", encoding="utf-8", newline="").write(
        json.dumps(payload, indent=1, ensure_ascii=False))

    print(f"parsed {len(rows)} APIs across {len(cats)} categories -> {OUT}")
    print("auth breakdown:", dict(sorted(auths.items(), key=lambda x: -x[1])))
    print("largest categories:",
          dict(sorted(cats.items(), key=lambda x: -x[1])[:8]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
