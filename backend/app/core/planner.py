"""Planner: work out what will happen before anything runs.

Given a goal it produces a reviewable plan: complexity, subtasks, the agent
and tool for each, estimated cost, runtime and confidence, and the order the
steps depend on each other. /api/agent/act runs instructions directly; this
lets a plan be read or refused first.

Deterministic on purpose, so it still works when the LLM provider is what's
broken. Decomposition is rule-based over the tools Titan actually has; the
LLM only enriches an existing plan.

Runtime uses measured tool latency where routing has data and is labelled a
default where it doesn't. Confidence drops when a step needs a tool that
isn't configured.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Optional

from . import events, tools

# Complexity bands: how many steps, and how much touches the network.
TRIVIAL, SIMPLE, MODERATE, COMPLEX = "trivial", "simple", "moderate", "complex"


@dataclass
class Step:
    id: str
    action: str
    specialist: str
    tool: str = ""
    depends_on: tuple = ()
    est_seconds: float = 1.0
    est_basis: str = "default"       # "measured" | "default"
    blocked_reason: str = ""

    def as_dict(self) -> dict:
        return {
            "id": self.id, "action": self.action, "specialist": self.specialist,
            "tool": self.tool, "depends_on": list(self.depends_on),
            "est_seconds": round(self.est_seconds, 1),
            "est_basis": self.est_basis,
            "blocked": bool(self.blocked_reason),
            "blocked_reason": self.blocked_reason,
        }


@dataclass
class Plan:
    goal: str
    steps: list = field(default_factory=list)
    complexity: str = SIMPLE
    confidence: float = 0.5
    created_at: float = field(default_factory=time.time)

    # -- derived -----------------------------------------------------------
    @property
    def blocked_steps(self) -> list:
        return [s for s in self.steps if s.blocked_reason]

    @property
    def est_seconds(self) -> float:
        """Critical path, not the sum: independent steps can run in parallel."""
        if not self.steps:
            return 0.0
        by_id = {s.id: s for s in self.steps}
        memo: dict[str, float] = {}

        def cost(sid: str, seen: frozenset = frozenset()) -> float:
            if sid in memo:
                return memo[sid]
            if sid in seen:            # a cycle would otherwise recurse forever
                return 0.0
            step = by_id.get(sid)
            if step is None:
                return 0.0
            upstream = max(
                [cost(d, seen | {sid}) for d in step.depends_on] or [0.0])
            memo[sid] = upstream + step.est_seconds
            return memo[sid]

        return max(cost(s.id) for s in self.steps)

    def as_dict(self) -> dict:
        return {
            "goal": self.goal,
            "complexity": self.complexity,
            "confidence": round(self.confidence, 2),
            "steps": [s.as_dict() for s in self.steps],
            "step_count": len(self.steps),
            "est_seconds": round(self.est_seconds, 1),
            "blocked": [s.as_dict() for s in self.blocked_steps],
            "executable": not self.blocked_steps,
            "graph": {s.id: list(s.depends_on) for s in self.steps},
            "note": ("Estimates are estimates. Runtime is the critical path "
                     "using measured tool latency where available, and a "
                     "default where not — each step says which."),
        }


# ------------------------------------------------------------ decomposition --
# Intent -> the steps Titan can actually take. First match wins, so specific
# patterns go first.
_INTENTS = (
    ("audit", r"\b(audit|seo|rank|ranking|compliance|impressum|legal)\b"),
    ("content", r"\b(post|caption|content|write|draft|social)\b"),
    ("research", r"\b(research|competitor|find out|investigate|analy[sz]e)\b"),
    ("outreach", r"\b(email|message|whatsapp|contact|reach out|outreach)\b"),
    ("report", r"\b(report|pdf|summary|summarise|summarize)\b"),
)


def classify(goal: str) -> str:
    low = (goal or "").lower()
    for name, pattern in _INTENTS:
        if re.search(pattern, low):
            return name
    return "general"


def _measured_seconds(tool_name: str) -> tuple:
    """(seconds, basis), using the tool layer's recorded latency when there is one."""
    from . import events as bus
    samples = [
        e["payload"].get("elapsed_ms", 0)
        for e in bus.trace(limit=200)
        if e["event"] in (bus.TOOL_INVOKED, bus.TOOL_FAILED)
        and e["payload"].get("tool") == tool_name
    ]
    samples = [s for s in samples if s > 0]
    if len(samples) >= 3:
        samples.sort()
        return samples[len(samples) // 2] / 1000.0, "measured"
    return 2.0, "default"


def _step(sid: str, action: str, specialist: str, tool: str = "",
          depends_on: tuple = ()) -> Step:
    seconds, basis = (_measured_seconds(tool) if tool else (0.5, "default"))
    blocked = ""
    if tool:
        t = tools.get(tool)
        if t is None:
            blocked = f"No such tool: {tool}"
        elif t.status() == "licence_blocked":
            blocked = f"{tool}: blocked on licence, not on engineering"
        elif t.status() == "not_configured":
            missing = ", ".join(t.missing_env() + t.missing_packages())
            blocked = f"{tool}: not configured — needs {missing}"
    return Step(sid, action, specialist, tool, depends_on, seconds, basis, blocked)


_RECIPES = {
    "audit": lambda: [
        _step("s1", "Fetch the target page", "seo-analyst", "web.fetch"),
        _step("s2", "Score technical, local and legal signals", "seo-analyst",
              depends_on=("s1",)),
        _step("s3", "Rank findings by cost of not fixing them", "seo-analyst",
              depends_on=("s2",)),
        _step("s4", "Produce the client-facing report", "report-writer",
              depends_on=("s3",)),
    ],
    "content": lambda: [
        _step("s1", "Load brand voice and forbidden phrasing", "brand-lead"),
        _step("s2", "Draft the post in market language", "content-writer",
              depends_on=("s1",)),
        _step("s3", "Validate against the brand rules", "brand-lead",
              depends_on=("s2",)),
        _step("s4", "Queue for approval — never auto-publish", "publisher",
              depends_on=("s3",)),
    ],
    "research": lambda: [
        _step("s1", "Crawl the sources", "researcher", "web.crawl"),
        _step("s2", "Extract claims with citations", "researcher",
              depends_on=("s1",)),
        _step("s3", "Summarise what is actually supported", "analyst",
              depends_on=("s2",)),
    ],
    "outreach": lambda: [
        _step("s1", "Draft the message", "content-writer"),
        _step("s2", "Human review — required before anything is sent",
              "founder", depends_on=("s1",)),
        _step("s3", "Send on approval", "messenger", "messaging.whatsapp",
              depends_on=("s2",)),
    ],
    "report": lambda: [
        _step("s1", "Gather the underlying numbers", "analyst"),
        _step("s2", "Render the report", "report-writer", depends_on=("s1",)),
    ],
    "general": lambda: [
        _step("s1", "Interpret the request", "chief-of-staff"),
        _step("s2", "Carry out the work", "chief-of-staff", depends_on=("s1",)),
    ],
}


def _complexity(steps: list) -> str:
    networked = sum(1 for s in steps if s.tool)
    if len(steps) <= 2 and not networked:
        return TRIVIAL
    if len(steps) <= 3:
        return SIMPLE
    if networked >= 2 or len(steps) >= 5:
        return COMPLEX
    return MODERATE


def _confidence(steps: list, intent: str) -> float:
    """Start from how well the goal was understood, then subtract for what can't run."""
    score = 0.85 if intent != "general" else 0.45
    blocked = sum(1 for s in steps if s.blocked_reason)
    if blocked:
        # Steps that can't run lower the confidence.
        score -= min(0.6, 0.25 * blocked)
    guessed = sum(1 for s in steps if s.est_basis == "default" and s.tool)
    score -= 0.05 * guessed
    return max(0.05, min(0.95, score))


def plan(goal: str) -> Plan:
    """Produce a reviewable plan. Never raises and never executes anything."""
    goal = (goal or "").strip()
    intent = classify(goal)
    steps = _RECIPES[intent]()

    # Apply the reflection correction: how far past estimates were off. It is
    # exactly 1.0 until there is enough evidence, so early plans are unchanged.
    from . import reflection
    factor = reflection.calibration()
    if factor != 1.0:
        for s in steps:
            s.est_seconds = round(s.est_seconds * factor, 2)
            s.est_basis = f"{s.est_basis}+calibrated"

    p = Plan(goal=goal, steps=steps,
             complexity=_complexity(steps),
             confidence=_confidence(steps, intent))
    events.emit(events.PLAN_CREATED, {
        "goal": goal[:200], "intent": intent, "steps": len(steps),
        "complexity": p.complexity, "confidence": round(p.confidence, 2),
        "blocked": len(p.blocked_steps),
    }, actor="planner")
    return p
