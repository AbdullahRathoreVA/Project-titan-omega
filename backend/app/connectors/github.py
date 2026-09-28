"""GitHub connector.

Pulls live repository stats from the GitHub REST API for the repos in
WATCHED. Read-only. Private repos need GITHUB_TOKEN. If a repo can't be
reached, the connector keeps its last known values.
"""

from __future__ import annotations

import os
from typing import List, Optional, Tuple

from ..domain.enums import ConnectorKind, ConnectorStatus
from ..store import STORE, Store, now

# (owner, repo) pairs to monitor. Add more here or with add_watch().
WATCHED: List[Tuple[str, str]] = [
    ("AbdullahRathoreVA", "career-mind"),
    ("AbdullahRathoreVA", "Project-titan-omega"),
]

_API = "https://api.github.com/repos/{owner}/{repo}"


def _verify():
    # Use the local proxy's CA bundle when one is present; plain TLS otherwise.
    bundle = os.getenv("TITAN_CA_BUNDLE") or "/root/.ccr/ca-bundle.crt"
    if os.path.exists(bundle):
        import ssl

        return ssl.create_default_context(cafile=bundle)
    return True


def fetch_repo(owner: str, repo: str) -> Optional[dict]:
    """Fetch one repo's live stats, or ``None`` if it can't be reached."""
    try:
        import httpx

        headers = {"Accept": "application/vnd.github+json"}
        token = os.getenv("GITHUB_TOKEN", "").strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"

        # trust_env picks up HTTPS_PROXY automatically in proxied environments;
        # follow_redirects handles repo renames / case differences (301).
        with httpx.Client(
            timeout=8.0, verify=_verify(), trust_env=True, follow_redirects=True
        ) as client:
            resp = client.get(_API.format(owner=owner, repo=repo), headers=headers)
        if resp.status_code != 200:
            return None
        data = resp.json()
        # Guard against proxy/error bodies that return 200 without repo fields.
        if not isinstance(data, dict) or "full_name" not in data:
            return None
        return data
    except Exception:
        return None


def _days_since(iso: Optional[str]) -> float:
    if not iso:
        return 0.0
    from datetime import datetime, timezone

    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return round((datetime.now(timezone.utc) - dt).total_seconds() / 86400, 1)
    except Exception:
        return 0.0


def refresh(store: Store = STORE) -> List[dict]:
    """Sync every watched repo into the connector registry with live metrics."""
    updated: List[dict] = []
    for owner, repo in WATCHED:
        data = fetch_repo(owner, repo)
        cid = f"gh-{owner}-{repo}".lower()
        existing = store.connectors.get(cid, {})

        if data is None:
            # Couldn't reach it - mark the status and keep any earlier metrics.
            conn = {
                **existing,
                "id": cid,
                "name": f"{owner}/{repo}",
                "kind": ConnectorKind.GITHUB,
                "status": ConnectorStatus.ERROR if existing else ConnectorStatus.DISCONNECTED,
                "url": f"https://github.com/{owner}/{repo}",
                "discovered_at": existing.get("discovered_at", now()),
                "last_sync": existing.get("last_sync"),
                "metrics": existing.get("metrics", {}),
            }
            store.connectors[cid] = conn
            store.emit("technology-repository-monitor", "connector",
                       f"Could not reach {owner}/{repo} (private? set GITHUB_TOKEN).", "warn")
            continue

        metrics = {
            "stars": float(data.get("stargazers_count", 0)),
            "forks": float(data.get("forks_count", 0)),
            "open_issues": float(data.get("open_issues_count", 0)),
            "watchers": float(data.get("subscribers_count", data.get("watchers_count", 0))),
            "size_kb": float(data.get("size", 0)),
            "days_since_push": _days_since(data.get("pushed_at")),
        }
        conn = {
            "id": cid,
            "name": data.get("full_name", f"{owner}/{repo}"),
            "kind": ConnectorKind.GITHUB,
            "status": ConnectorStatus.CONNECTED,
            "url": data.get("html_url", f"https://github.com/{owner}/{repo}"),
            "discovered_at": existing.get("discovered_at", now()),
            "last_sync": now(),
            "metrics": metrics,
        }
        store.connectors[cid] = conn
        updated.append(conn)
        store.emit(
            "technology-repository-monitor",
            "connector",
            f"Synced {conn['name']} · {int(metrics['open_issues'])} open issues · "
            f"last push {metrics['days_since_push']:.0f}d ago.",
            "success",
        )
    return updated
