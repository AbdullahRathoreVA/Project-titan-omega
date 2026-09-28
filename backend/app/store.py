"""In-memory runtime state for the platform."""

from __future__ import annotations

import contextvars
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
    # Workflow position: which stage of the division's pipeline the agent is on,
    # and progress (0..1) through it.
    step: int = 0
    progress: float = 0.0


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
    # Append-only ledger of real orders and sales (see the revenue routes).
    revenue_entries: List[dict] = field(default_factory=list)
    # Current "next post" draft (caption + AI image) shown on the dashboard.
    next_post: Optional[dict] = None
    # Latest growth research (opportunities, competitors, keywords).
    intel: Optional[dict] = None
    # Telegram: last processed update id, and the command/reply log.
    telegram_offset: int = 0
    telegram_log: List[dict] = field(default_factory=list)
    # Job Radar: found jobs/gigs with scores and applied status.
    jobs: Optional[dict] = None
    # Expense ledger (revenue lives in revenue_entries).
    expenses: List[dict] = field(default_factory=list)
    # CRM-lite: leads pipeline keyed by id.
    leads: Dict[str, dict] = field(default_factory=dict)
    # Latest war-room decision waiting for the founder's approval (sent to Telegram).
    pending_decision: Optional[dict] = None
    # History of war-room decisions.
    decisions: List[dict] = field(default_factory=list)

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


# --- which Store a request sees -------------------------------------------
# The founder's Store is the default. A subscriber request binds that
# subscriber's workspace for its duration (see main.auth_guard and
# core/workspaces.py), and everything that uses STORE follows the binding.
# Threads started with contextvars.copy_context() carry it, as do
# asyncio.to_thread and Starlette's threadpool.
_FOUNDER = Store()
_bound: "contextvars.ContextVar[Optional[Store]]" = contextvars.ContextVar(
    "titan_store", default=None)


def founder_store() -> Store:
    return _FOUNDER


def current() -> Store:
    bound = _bound.get()
    return bound if bound is not None else _FOUNDER


def bind(store: Store) -> "contextvars.Token":
    return _bound.set(store)


def unbind(token: "contextvars.Token") -> None:
    _bound.reset(token)


class _StoreProxy:
    """Stands in for the Store every module imports as STORE.

    Hundreds of call sites use `from ..store import STORE`. Making that name
    follow the bound workspace keeps them unchanged, and a subscriber request
    can't reach the founder's Store by forgetting to pass one.
    """

    __slots__ = ()

    def __getattr__(self, name):
        return getattr(current(), name)

    def __setattr__(self, name, value):
        setattr(current(), name, value)

    def __repr__(self) -> str:
        return f"<STORE -> {'workspace' if _bound.get() is not None else 'founder'}>"


STORE = _StoreProxy()


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
            "cm_revenue": 0.0,
            "kindle_units_sold": 0.0,
            "kindle_royalties": 0.0,
            "kindle_reviews": 0.0,
            "other_revenue": 0.0,
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
            "Writing Upwork gig description optimisation",
            "Researching competitor pricing on Upwork",
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
            "Scanning Upwork category trends",
            "Surfacing high-demand AI gig niches",
            "Aggregating student platform market signals",
            "Monitoring Amazon Kindle bestseller rankings in AI career category",
        ],
        "revenue": [
            "Identifying first 10 potential Upwork clients",
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
            "Upwork Profile",
            ConnectorKind.MARKETPLACE,
            "https://www.upwork.com/freelancers/~01afb00378bd38d964?mp_source=share",
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
