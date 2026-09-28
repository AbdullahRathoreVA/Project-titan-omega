"""Enumerations shared across the platform: divisions, agent autonomy, and the
states opportunities and executions move through.
"""

from __future__ import annotations

from enum import Enum


class AutonomyLevel(str, Enum):
    """How far an agent may act without human sign-off.

    Set per agent rather than globally, so the highest-impact actions keep a
    human in the loop.
    """

    OBSERVE = "observe"          # read-only: gather signal, never act
    SUGGEST = "suggest"          # draft actions, require human approval
    EXECUTE = "execute"          # act autonomously within guardrails
    AUTONOMOUS = "autonomous"    # act and self-direct toward goals


class AgentStatus(str, Enum):
    IDLE = "idle"
    WORKING = "working"
    BLOCKED = "blocked"
    OFFLINE = "offline"


class Division(str, Enum):
    """The divisions of the company. Every agent belongs to one."""

    EXECUTIVE = "executive"
    OPERATIONS = "operations"
    FINANCE = "finance"
    MARKETING = "marketing"
    TECHNOLOGY = "technology"
    PRODUCT = "product"
    REVENUE = "revenue"
    GROWTH = "growth"
    INTELLIGENCE = "intelligence"
    CUSTOMER = "customer"
    PARTNERSHIPS = "partnerships"
    INNOVATION = "innovation"


class OpportunityStatus(str, Enum):
    DISCOVERED = "discovered"
    SCORED = "scored"
    QUEUED = "queued"
    IN_PROGRESS = "in_progress"
    REALIZED = "realized"
    DISMISSED = "dismissed"


class ExecutionStatus(str, Enum):
    """Lifecycle of an autonomous action. Every action is logged and reversible."""

    PENDING = "pending"          # awaiting approval (for SUGGEST agents)
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    REVERTED = "reverted"
    CANCELLED = "cancelled"


class ConnectorKind(str, Enum):
    GITHUB = "github"
    WEB_APP = "web_app"
    SAAS = "saas"
    LANDING_PAGE = "landing_page"
    ANALYTICS = "analytics"
    EMAIL = "email"
    SOCIAL = "social"
    CRM = "crm"
    ADS = "ads"
    MARKETPLACE = "marketplace"


class ConnectorStatus(str, Enum):
    DISCOVERED = "discovered"
    CONNECTED = "connected"
    SYNCING = "syncing"
    ERROR = "error"
    DISCONNECTED = "disconnected"


class Horizon(str, Enum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
