"""Live Career Mind AI connector.

Monitors the Career Mind AI platform — the primary product asset — by polling
its public health endpoint and, when an admin token is available, its usage
stats. The live HF Space is used by default; override with ``CAREERMIND_URL``.

Degrades gracefully: on any network failure the last-known metrics are kept and
the connector status is set to DISCONNECTED so the dashboard never breaks.
"""

from __future__ import annotations

import os
import ssl
from typing import Optional

from ..domain.enums import ConnectorKind, ConnectorStatus
from ..store import STORE, Store, now

_BASE_URL = os.getenv("CAREERMIND_URL", "https://careermind2026-career-mind.hf.space")
_CONN_ID  = "careermind-main"


def _verify():
    bundle = os.getenv("TITAN_CA_BUNDLE") or "/root/.ccr/ca-bundle.crt"
    if os.path.exists(bundle):
        return ssl.create_default_context(cafile=bundle)
    return True


def _get(path: str, token: Optional[str] = None) -> Optional[dict]:
    """GET a JSON endpoint; returns the parsed body or None on any error."""
    try:
        import httpx

        headers = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        with httpx.Client(
            timeout=10.0, verify=_verify(), trust_env=True, follow_redirects=True
        ) as client:
            resp = client.get(f"{_BASE_URL}{path}", headers=headers)
        if resp.status_code == 200:
            data = resp.json()
            return data if isinstance(data, dict) else None
    except Exception:
        pass
    return None


def refresh(store: Store = STORE) -> Optional[dict]:
    """Sync Career Mind AI metrics into the connector registry."""
    existing = store.connectors.get(_CONN_ID, {})
    token    = os.getenv("CAREERMIND_API_KEY")

    # 1. Public health probe — confirms the platform is reachable.
    health = _get("/health")

    if health is None:
        conn = {
            **existing,
            "id":            _CONN_ID,
            "name":          "Career Mind AI",
            "kind":          ConnectorKind.WEB_APP,
            "status":        ConnectorStatus.DISCONNECTED,
            "url":           _BASE_URL,
            "discovered_at": existing.get("discovered_at", now()),
            "last_sync":     existing.get("last_sync"),
            "metrics":       existing.get("metrics", _default_metrics()),
        }
        store.connectors[_CONN_ID] = conn
        store.emit(
            "product-retention-analyst", "connector",
            "Career Mind AI unreachable — keeping cached metrics.", "warn",
        )
        return None

    # 2. Start from defaults / cached values; mark platform online.
    metrics = dict(existing.get("metrics", _default_metrics()))
    metrics["platform_online"] = 1.0

    # 3. Enrich with live usage stats when an admin token is configured.
    if token:
        stats = _get("/api/admin/stats", token=token)
        if stats:
            metrics.update({
                "total_users":    float(stats.get("total_users",      metrics.get("total_users",    0))),
                "active_users":   float(stats.get("active_users_30d", metrics.get("active_users",   0))),
                "career_matches": float(stats.get("career_analyses",  metrics.get("career_matches", 0))),
                "signups":        float(stats.get("new_signups_7d",   metrics.get("signups",        0))),
            })
        else:
            store.emit(
                "product-retention-analyst", "connector",
                "Career Mind AI: /api/admin/stats unavailable — token invalid?", "warn",
            )

    conn = {
        "id":            _CONN_ID,
        "name":          "Career Mind AI",
        "kind":          ConnectorKind.WEB_APP,
        "status":        ConnectorStatus.CONNECTED,
        "url":           _BASE_URL,
        "discovered_at": existing.get("discovered_at", now()),
        "last_sync":     now(),
        "metrics":       metrics,
    }
    store.connectors[_CONN_ID] = conn
    store.emit(
        "product-retention-analyst", "connector",
        f"Career Mind AI synced · platform online · "
        f"{int(metrics.get('total_users', 0)):,} total users.",
        "success",
    )
    return conn


def _default_metrics() -> dict:
    """Seed values shown before the first successful live sync."""
    return {
        "traffic":         142_000.0,
        "signups":           3_800.0,
        "conversion":            4.1,
        "retention":            61.0,
        "platform_online":       0.0,
        "total_users":       3_800.0,
        "active_users":      1_200.0,
        "career_matches":   18_000.0,
    }
