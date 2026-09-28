"""Tunes opportunity scoring from real outcomes.

When an execution succeeds, fails or is reverted, the scoring weights are
nudged so future scores reflect results rather than hand-set priors. Weights
live in STORE.metrics under weight_* keys (no import cycles with the
opportunity engine). Each adjustment is small and bounded.
"""

from __future__ import annotations

from typing import Optional

from ..store import STORE, Store

# Keys in STORE.metrics; they match the penalty terms in opportunity.score().
_W_DIFFICULTY = "weight_difficulty"
_W_RISK       = "weight_risk"
_W_TIME       = "weight_time"

# Priors; must match the defaults in opportunity.score().
_DEFAULTS = {
    _W_DIFFICULTY: 0.35,
    _W_RISK:       0.25,
    _W_TIME:       0.15,
}

_STEP = 0.005   # max nudge per event
_MIN  = 0.05    # floor: a penalty never disappears
_MAX  = 0.60    # ceiling: a penalty never dominates


def ensure_weights(store: Store = STORE) -> None:
    """Seed weight metrics with priors if not already present."""
    for key, default in _DEFAULTS.items():
        store.metrics.setdefault(key, default)


def record_outcome(
    opportunity_id: str,
    success: bool,
    store: Store = STORE,
) -> None:
    """Adjust scoring weights after a real execution outcome.

    success=True  -> we were too cautious; nudge the dominant penalty down.
    success=False -> the risk or difficulty was real; nudge it up.
    """
    ensure_weights(store)
    opp = store.opportunities.get(opportunity_id)
    if opp is None:
        return

    sign = -1 if success else +1

    # Find which penalty was most influential for this specific opportunity.
    candidates = [
        (_W_DIFFICULTY, float(opp.get("difficulty",           50.0))),
        (_W_RISK,       float(opp.get("risk",                  25.0))),
        (_W_TIME,       min(float(opp.get("time_estimate_days", 14.0)) / 60.0 * 100, 100.0)),
    ]
    dominant = max(candidates, key=lambda pair: pair[1])[0]

    old = store.metrics[dominant]
    new = round(max(_MIN, min(_MAX, old + sign * _STEP)), 4)
    store.metrics[dominant] = new

    direction = "↓" if new < old else "↑"
    store.emit(
        "innovation-self-evolution-engine",
        "evolution",
        f"{'✓' if success else '✗'} '{opp['title'][:55]}' · "
        f"{dominant.replace('weight_', '')} weight {direction} {old:.3f}→{new:.3f}",
        "info",
    )


def weights(store: Store = STORE) -> dict:
    """Return the current scoring weight dict."""
    ensure_weights(store)
    return {k: store.metrics[k] for k in _DEFAULTS}


def adaptive_score(
    expected_revenue: float,
    difficulty: float,
    risk: float,
    time_days: float,
    store: Store = STORE,
) -> float:
    """Like opportunity.score() but uses live evolved weights instead of priors."""
    ensure_weights(store)
    w = weights(store)

    reward        = min(expected_revenue / 100_000, 1.0)
    difficulty_pen = (difficulty / 100) * w[_W_DIFFICULTY]
    risk_pen       = (risk / 100) * w[_W_RISK]
    time_pen       = min(time_days / 60, 1.0) * w[_W_TIME]

    raw = reward - difficulty_pen - risk_pen - time_pen
    return round(max(0.0, min(1.0, (raw + 0.75) / 1.75)) * 100, 1)
