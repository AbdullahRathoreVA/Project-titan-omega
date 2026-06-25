"""In-memory runtime state for the platform.

The production architecture targets PostgreSQL + Redis (see README), but the
runnable foundation keeps a single dependency-light, thread-safe store so the
whole system boots with nothing more than ``pip install -r requirements.txt``.
The store is intentionally hidden behind a small API so a database-backed
implementation can be swapped in without touching the engines or routes.
"""

from __future__ import annotations

import itertools
import random
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from .domain.enums import AgentStatus, ConnectorKind, ConnectorStatus
from .domain.network import AGENT_NETWORK, AgentSpec


def now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class AgentRuntime:
    """Mutable live state for a single agent, paired with its static spec."""

    spec: AgentSpec
    status: AgentStatus = AgentStatus.IDLE
    current_task: Optional[str] = None
    tasks_completed: int = 0
    success_rate: float = 0.0
    impact_score: float = 0.0
    last_active: Optional[datetime] = None


@dataclass
class Store:
    """Single process-wide state container.

    All mutating access goes through methods guarded by a re-entrant lock so the
    background heartbeat and request handlers can interleave safely.
    """

    agents: Dict[str, AgentRuntime] = field(default_factory=dict)
    opportunities: Dict[str, dict] = field(default_factory=dict)
    executions: Dict[str, dict] = field(default_factory=dict)
    connectors: Dict[str, dict] = field(default_factory=dict)
    deliverables: Dict[str, dict] = field(default_factory=dict)
    feed: List[dict] = field(default_factory=list)
    metrics: Dict[str, float] = field(default_factory=dict)

    _lock: threading.RLock = field(default_factory=threading.RLock)
    _ids: "itertools.count" = field(default_factory=lambda: itertools.count(1))
    _rng: random.Random = field(default_factory=lambda: random.Random(7))

    # ---- identifiers -----------------------------------------------------
    def new_id(self, prefix: str) -> str:
        with self._lock:
            return f"{prefix}-{next(self._ids):05d}"

    # ---- feed ------------------------------------------------------------
    def emit(self, actor: str, kind: str, message: str, severity: str = "info") -> dict:
        event = {
            "id": self.new_id("evt"),
            "timestamp": now(),
            "actor": actor,
            "kind": kind,
            "message": message,
            "severity": severity,
        }
        with self._lock:
            self.feed.append(event)
            # keep the live feed bounded
            if len(self.feed) > 500:
                self.feed = self.feed[-500:]
        return event

    def recent_feed(self, limit: int = 50) -> List[dict]:
        with self._lock:
            return list(reversed(self.feed[-limit:]))


# Process-wide singleton.
STORE = Store()


def seed(store: Store = STORE) -> None:
    """Populate the store with the agent network and a believable starting state.

    Deterministic (fixed RNG seed) so tests and demos are reproducible.
    """

    rng = store._rng
    store.agents.clear()

    for spec in AGENT_NETWORK:
        completed = rng.randint(3, 240)
        runtime = AgentRuntime(
            spec=spec,
            status=rng.choices(
                [AgentStatus.WORKING, AgentStatus.IDLE, AgentStatus.BLOCKED],
                weights=[6, 3, 1],
            )[0],
            current_task=_sample_task(spec, rng),
            tasks_completed=completed,
            success_rate=round(rng.uniform(0.78, 0.99), 3),
            impact_score=round(rng.uniform(40, 98), 1),
            last_active=now() - timedelta(minutes=rng.randint(0, 90)),
        )
        store.agents[spec.id] = runtime

    # Empire-level metrics — the headline numbers on the command center.
    store.metrics.update(
        {
            "mrr": 48230.0,
            "traffic": 184500.0,
            "pipeline_value": 312000.0,
            "customers": 1240.0,
            "conversion_rate": 3.4,
            "brand_value": 72.0,
        }
    )

    _seed_connectors(store)
    store.emit("executive-core", "system", "Executive Intelligence Core online.", "success")
    store.emit(
        "executive-core",
        "system",
        f"{len(store.agents)} digital employees across "
        f"{len({a.spec.division for a in store.agents.values()})} divisions reporting in.",
        "info",
    )


def _sample_task(spec: AgentSpec, rng: random.Random) -> Optional[str]:
    pool = {
        "marketing": [
            "Drafting Q3 content calendar",
            "Optimizing landing page headline",
            "Analyzing campaign CTR",
        ],
        "growth": [
            "Running funnel drop-off analysis",
            "Designing onboarding A/B test",
            "Auditing SEO keyword gaps",
        ],
        "intelligence": [
            "Scanning competitor pricing",
            "Surfacing emerging niche signals",
            "Aggregating market sentiment",
        ],
        "revenue": [
            "Qualifying inbound leads",
            "Drafting outreach sequence",
            "Updating deal pipeline",
        ],
        "technology": [
            "Monitoring repository health",
            "Reviewing CI pipeline status",
            "Scanning for security advisories",
        ],
    }
    options = pool.get(spec.division.value)
    if not options:
        return f"Advancing {spec.division.value} objectives"
    return rng.choice(options)


def _seed_connectors(store: Store) -> None:
    # GitHub repos are synced live by app.connectors.github at startup; these two
    # are placeholders for analytics/marketplace sources you'll connect later.
    seeds = [
        ("Career Mind AI", ConnectorKind.WEB_APP, "https://careermind.ai",
         {"traffic": 142000, "signups": 3800, "conversion": 4.1, "retention": 61.0}),
        ("Fiverr Gig Network", ConnectorKind.MARKETPLACE, "https://fiverr.com",
         {"impressions": 92000, "clicks": 4100, "orders": 210, "conversion": 5.1}),
    ]
    for name, kind, url, metrics in seeds:
        cid = store.new_id("conn")
        store.connectors[cid] = {
            "id": cid,
            "name": name,
            "kind": kind,
            "status": ConnectorStatus.CONNECTED,
            "url": url,
            "discovered_at": now(),
            "last_sync": now(),
            "metrics": metrics,
        }
