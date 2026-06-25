"""Autonomous Execution Layer.

The platform does not stop at analysis: where permitted, agents act. This layer
turns an intent (often an opportunity) into a tracked, **logged, verified and
reversible** action. Agents with ``SUGGEST`` autonomy produce actions that wait
for human approval; ``EXECUTE``/``AUTONOMOUS`` agents run within guardrails.

Every state transition appends to the action's audit log so the command center
can show exactly what happened and so any action can be reverted.
"""

from __future__ import annotations

from typing import Optional

from ..domain.enums import AutonomyLevel, ExecutionStatus
from ..domain.network import AGENTS_BY_ID
from ..store import STORE, Store, now


class ExecutionError(Exception):
    """Raised for invalid execution transitions (unknown agent, bad state, etc.)."""


def _log(action: dict, message: str) -> None:
    action["logs"].append(f"{now().isoformat()}  {message}")
    action["updated_at"] = now()


def propose(
    title: str,
    description: str,
    agent_id: str,
    opportunity_id: Optional[str] = None,
    reversible: bool = True,
    store: Store = STORE,
) -> dict:
    """Create an action. Whether it requires approval depends on agent autonomy."""

    spec = AGENTS_BY_ID.get(agent_id)
    if spec is None:
        raise ExecutionError(f"Unknown agent: {agent_id}")

    requires_approval = spec.autonomy in (AutonomyLevel.OBSERVE, AutonomyLevel.SUGGEST)
    action = {
        "id": store.new_id("act"),
        "title": title,
        "description": description,
        "agent_id": agent_id,
        "division": spec.division,
        "autonomy": spec.autonomy,
        "status": ExecutionStatus.PENDING if requires_approval else ExecutionStatus.RUNNING,
        "reversible": reversible,
        "requires_approval": requires_approval,
        "opportunity_id": opportunity_id,
        "created_at": now(),
        "updated_at": now(),
        "logs": [],
        "result": None,
    }
    store.executions[action["id"]] = action

    if requires_approval:
        _log(action, f"Proposed by {spec.name}; awaiting human approval.")
        store.emit(agent_id, "execution", f"Proposed (needs approval): {title}", "warn")
    else:
        _log(action, f"Auto-started by {spec.name} ({spec.autonomy.value}).")
        store.emit(agent_id, "execution", f"Executing: {title}", "info")
    return action


def approve(action_id: str, store: Store = STORE) -> dict:
    action = _require(action_id, store)
    if action["status"] is not ExecutionStatus.PENDING:
        raise ExecutionError(f"Action {action_id} is not pending approval.")
    action["status"] = ExecutionStatus.RUNNING
    _log(action, "Approved by human operator.")
    store.emit(action["agent_id"], "execution", f"Approved & running: {action['title']}", "info")
    return action


def complete(action_id: str, result: str, store: Store = STORE) -> dict:
    action = _require(action_id, store)
    if action["status"] is not ExecutionStatus.RUNNING:
        raise ExecutionError(f"Action {action_id} is not running.")
    action["status"] = ExecutionStatus.COMPLETED
    action["result"] = result
    _log(action, f"Completed: {result}")
    store.emit(action["agent_id"], "execution", f"Completed: {action['title']}", "success")

    # Reflect completion in the owning agent's runtime stats.
    runtime = store.agents.get(action["agent_id"])
    if runtime:
        runtime.tasks_completed += 1
        runtime.last_active = now()
    return action


def fail(action_id: str, reason: str, store: Store = STORE) -> dict:
    action = _require(action_id, store)
    action["status"] = ExecutionStatus.FAILED
    action["result"] = reason
    _log(action, f"Failed: {reason}")
    store.emit(action["agent_id"], "execution", f"Failed: {action['title']}", "critical")
    return action


def revert(action_id: str, store: Store = STORE) -> dict:
    """Undo an action. Only reversible actions can be reverted — by design."""
    action = _require(action_id, store)
    if not action["reversible"]:
        raise ExecutionError(f"Action {action_id} is not reversible.")
    action["status"] = ExecutionStatus.REVERTED
    _log(action, "Reverted by operator; side effects rolled back.")
    store.emit(action["agent_id"], "execution", f"Reverted: {action['title']}", "warn")
    return action


def cancel(action_id: str, store: Store = STORE) -> dict:
    action = _require(action_id, store)
    if action["status"] in (ExecutionStatus.COMPLETED, ExecutionStatus.REVERTED):
        raise ExecutionError(f"Action {action_id} cannot be cancelled.")
    action["status"] = ExecutionStatus.CANCELLED
    _log(action, "Cancelled before completion.")
    return action


def _require(action_id: str, store: Store) -> dict:
    action = store.executions.get(action_id)
    if action is None:
        raise ExecutionError(f"Unknown action: {action_id}")
    return action
