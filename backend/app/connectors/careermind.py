"""Live Career Mind AI connector.

Monitors the Career Mind AI platform — the primary product asset — by polling
its public ``/health`` probe and ``/api/public/stats`` aggregate endpoint (added
to Career Mind for exactly this purpose). No login required; the optional
``CAREERMIND_API_KEY`` is sent as ``X-Titan-Key`` when Career Mind has
``TITAN_STATS_KEY`` configured.

The live HF Space is used by default; override with ``CAREERMIND_URL``.

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


def _get(path: str, key: Optional[str] = None) -> Optional[dict]:
    """GET a JSON endpoint; returns the parsed body or None on any error."""
    try:
        import httpx

        headers = {"Accept": "application/json"}
        if key:
            headers["X-Titan-Key"] = key
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
    key      = os.getenv("CAREERMIND_API_KEY")  # optional X-Titan-Key

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

    # 3. Pull live aggregate usage from the public stats endpoint.
    stats = _get("/api/public/stats", key=key)
    if stats:
        total = float(stats.get("total_users", metrics.get("total_users", 0)))
        active = float(stats.get("active_users_30d") or stats.get("active_users", metrics.get("active_users", 0)))
        metrics.update({
            "total_users":    total,
            "active_users":   active,
            "signups":        float(stats.get("new_signups_7d", metrics.get("signups", 0))),
            "career_matches": float(stats.get("career_analyses", metrics.get("career_matches", 0))),
            "traffic":        total,  # surface user count as the headline number
        })
    else:
        store.emit(
            "product-retention-analyst", "connector",
            "Career Mind AI: /api/public/stats unavailable — deploy the latest Career Mind build.", "warn",
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

    # Mirror Career Mind numbers into empire-level metrics for the dashboard.
    store.metrics["cm_traffic"]      = metrics.get("total_users", 0.0)
    store.metrics["cm_signups"]      = metrics.get("signups", 0.0)
    store.metrics["cm_active_users"] = metrics.get("active_users", 0.0)

    store.emit(
        "product-retention-analyst", "connector",
        f"Career Mind AI synced · {int(metrics.get('total_users', 0)):,} users · "
        f"{int(metrics.get('active_users', 0)):,} active.",
        "success",
    )
    return conn


def _default_metrics() -> dict:
    """Zero-based seed — real numbers arrive on the first successful live sync."""
    return {
        "traffic":         0.0,
        "signups":         0.0,
        "conversion":      0.0,
        "retention":       0.0,
        "platform_online": 0.0,
        "total_users":     0.0,
        "active_users":    0.0,
        "career_matches":  0.0,
    }
