"""In-memory runtime state for the platform."""

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
    spec: AgentSpec
    status: AgentStatus = AgentStatus.IDLE
    current_task: Optional[str] = None
    tasks_completed: int = 0
    success_rate: float = 0.0
    impact_score: float = 0.0
    last_active: Optional[datetime] = None


@dataclass
class Store:
    agents: Dict[str, AgentRuntime] = field(default_factory=dict)
    opportunities: Dict[str, dict] = field(default_factory=dict)
    executions: Dict[str, dict] = field(default_factory=dict)
    connectors: Dict[str, dict] = field(default_factory=dict)
    deliverables: Dict[str, dict] = field(default_factory=dict)
    posts: Dict[str, dict] = field(default_factory=dict)
    feed: List[dict] = field(default_factory=list)
    metrics: Dict[str, float] = field(default_factory=dict)

    _lock: threading.RLock = field(default_factory=threading.RLock)
    _ids: "itertools.count" = field(default_factory=lambda: itertools.count(1))
    _rng: random.Random = field(default_factory=lambda: random.Random(7))

    def new_id(self, prefix: str) -> str:
        with self._lock:
            return f"{prefix}-{next(self._ids):05d}"

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
            if len(self.feed) > 500:
                self.feed = self.feed[-500:]
        return event

    def recent_feed(self, limit: int = 50) -> List[dict]:
        with self._lock:
            return list(reversed(self.feed[-limit:]))


STORE = Store()


def seed(store: Store = STORE) -> None:
    rng = store._rng
    store.agents.clear()

    for spec in AGENT_NETWORK:
        completed = rng.randint(0, 12)
        runtime = AgentRuntime(
            spec=spec,
            status=rng.choices(
                [AgentStatus.WORKING, AgentStatus.IDLE, AgentStatus.BLOCKED],
                weights=[7, 2, 1],
            )[0],
            current_task=_sample_task(spec, rng),
            tasks_completed=completed,
            success_rate=round(rng.uniform(0.80, 0.99), 3),
            impact_score=round(rng.uniform(20, 70), 1),
            last_active=now() - timedelta(minutes=rng.randint(0, 30)),
        )
        store.agents[spec.id] = runtime

    store.metrics.update(
        {
            "mrr": 0.0,
            "traffic": 0.0,
            "pipeline_value": 0.0,
            "customers": 0.0,
            "conversion_rate": 0.0,
            "brand_value": 0.0,
            "cm_traffic": 0.0,
            "cm_signups": 0.0,
            "cm_active_users": 0.0,
            "fiverr_orders": 0.0,
            "fiverr_impressions": 0.0,
            "fiverr_revenue": 0.0,
            "kindle_units_sold": 0.0,
            "kindle_royalties": 0.0,
            "kindle_reviews": 0.0,
        }
    )

    _seed_connectors(store)
    store.emit("executive-core", "system", "Executive Intelligence Core online. Abdullah — your empire starts NOW.", "success")
    store.emit(
        "executive-core",
        "system",
        f"{len(store.agents)} digital employees across "
        f"{len({a.spec.division for a in store.agents.values()})} divisions reporting for duty.",
        "info",
    )
    store.emit("executive-core", "system", "All metrics at zero — real data only. Update via Make.com webhooks.", "info")


def _sample_task(spec: AgentSpec, rng: random.Random) -> Optional[str]:
    pool = {
        "marketing": [
            "Drafting LinkedIn post for Career Mind launch",
            "Writing Fiverr gig description optimisation",
            "Researching competitor pricing on Fiverr",
            "Creating social media content calendar",
            "Researching school/university outreach strategy",
            "Writing cold email templates for Career Mind B2B",
        ],
        "growth": [
            "Analysing Career Mind signup funnel",
            "Identifying free traffic channels",
            "Designing first A/B test for landing page",
            "Mapping zero-cost acquisition strategies",
            "Building student audience targeting model",
        ],
        "intelligence": [
            "Scanning Fiverr category trends",
            "Surfacing high-demand AI gig niches",
            "Aggregating student platform market signals",
            "Monitoring Amazon Kindle bestseller rankings in AI career category",
        ],
        "revenue": [
            "Identifying first 10 potential Fiverr clients",
            "Drafting outreach message templates",
            "Building lead qualification criteria",
            "Researching Amazon KDP royalty optimisation",
        ],
        "technology": [
            "Monitoring Career Mind HF Space uptime",
            "Reviewing CI pipeline status",
            "Scanning dependencies for security advisories",
        ],
    }
    options = pool.get(spec.division.value)
    if not options:
        return f"Advancing {spec.division.value} objectives toward first revenue"
    return rng.choice(options)


def _seed_connectors(store: Store) -> None:
    seeds = [
        (
            "Career Mind AI",
            ConnectorKind.WEB_APP,
            "https://careermind2026-career-mind.hf.space",
            {"traffic": 0, "signups": 0, "conversion": 0.0, "retention": 0.0,
             "total_users": 0.0, "active_users": 0.0},
        ),
        (
            "Fiverr Gig Network",
            ConnectorKind.MARKETPLACE,
            "https://fiverr.com",
            {"impressions": 0, "clicks": 0, "orders": 0, "revenue": 0.0},
        ),
        (
            "Amazon Kindle Book",
            ConnectorKind.MARKETPLACE,
            "https://kdp.amazon.com",
            {"units_sold": 0, "royalties": 0.0, "reviews": 0, "ranking": 0},
        ),
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
