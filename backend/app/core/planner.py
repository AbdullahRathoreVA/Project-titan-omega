"""Planning engine — decide before doing.

Spec Part 2: "Every request must go through planning. The planner must:
understand the goal, estimate complexity, break into subtasks, assign
specialists, estimate cost, estimate runtime, estimate confidence, choose
models, choose tools, generate execution graph — BEFORE execution begins."

The important word is *before*. Titan already executes: `/api/agent/act` routes
an instruction straight to an agent and runs it. Nothing states what it intends
to do, what it will cost, or how sure it is, so nothing can be reviewed or
refused first. This produces that statement.

Deliberately deterministic. An LLM could write prettier plans, but a planner
that needs a working API key cannot plan the recovery when the API key is what
broke — and Titan's whole design is that it degrades to real work with no
provider configured. The decomposition here is rule-based over the capabilities
Titan actually has; `llm` is used only to enrich a plan that already exists.

Estimates are honest about being estimates. Runtime comes from measured tool
latency where routing has data, and is labelled a guess where it does not.
Confidence falls when a step depends on a tool that is not configured, because
a plan whose third step needs a key nobody has set is not a 90%-confidence plan.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Optional

from . import events, tools

# Complexity bands, in the only unit that matters here: how many steps and how
# much of it touches the network.
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
        """Critical path, not the sum: independent steps can run together."""
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


# ------------------------------------------------------------- decomposition --
# Intent -> the sequence of things Titan can actually do. Ordered: the first
# match wins, so put the specific patterns first.
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
    """(seconds, basis). Uses the tool layer's own recorded latency if present."""
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
    """Start from how well the goal was understood, then subtract for reality."""
    score = 0.85 if intent != "general" else 0.45
    blocked = sum(1 for s in steps if s.blocked_reason)
    if blocked:
        # A plan whose steps cannot run is not a confident plan, however tidy.
        score -= min(0.6, 0.25 * blocked)
    guessed = sum(1 for s in steps if s.est_basis == "default" and s.tool)
    score -= 0.05 * guessed
    return max(0.05, min(0.95, score))


def plan(goal: str) -> Plan:
    """Produce a reviewable plan. Never raises, never executes anything."""
    goal = (goal or "").strip()
    intent = classify(goal)
    steps = _RECIPES[intent]()

    # Close the reflection loop. Reflection measures how far past estimates
    # missed and returns a correction; applying it here is the only thing that
    # makes reflection a feedback loop rather than a diary. The factor is
    # exactly 1.0 until there is enough evidence, so early plans are untouched.
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
