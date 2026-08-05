"""Self-reflection — learn from what actually happened.

Spec Part 2: "Every completed task enters Reflection. Reflection asks: Was the
objective achieved? Were mistakes made? Can prompts improve? Can routing
improve? Should memory be updated?... Reflection continuously improves future
performance."

The last sentence is the whole test. A reflection module that writes "task
completed successfully" into a log improves nothing — it is a diary, not a
feedback loop. For this to earn its place, something downstream has to behave
differently because of what it recorded.

So the loop closes on one concrete, measurable thing: **the planner's
estimates**. The planner already commits to a runtime and a confidence before
executing (core/planner.py). Reflection measures what actually happened,
computes the bias, and hands back a calibration factor the planner applies to
its next estimate. An estimator that says 3 seconds and takes 30 is not
"roughly right" — it is wrong in a way that makes every downstream decision
wrong, and it is only fixable if someone is keeping score.

Deliberate choices:

  Calibration needs evidence. Below MIN_SAMPLES the factor is exactly 1.0 —
  one slow network call must not permanently triple every future estimate.

  The factor is clamped. Even with a pathological history the planner is never
  told to multiply by 50; a wild correction is less useful than a mild one and
  far harder to debug.

  The median is used, not the mean. One 30-second timeout in a set of
  half-second tasks would drag a mean far enough to poison every estimate.

  Confidence is scored against OUTCOMES, not against itself. A plan that was
  90% confident and failed is a worse error than one that was 40% confident and
  failed, and the Brier score is the standard way to say so numerically.
"""

from __future__ import annotations

import statistics
import threading
import time
from typing import Optional

from . import events

MIN_SAMPLES = 5           # before estimates are corrected at all
MAX_HISTORY = 200         # bounded: small container
CALIBRATION_FLOOR = 0.25  # never shrink an estimate by more than 4x
CALIBRATION_CEIL = 4.0    # never inflate it by more than 4x

_lock = threading.RLock()
_records: list[dict] = []


def record(*, goal: str, achieved: bool, predicted_seconds: float,
           actual_seconds: float, confidence: float = 0.5,
           tool_failures: Optional[list] = None,
           provider: str = "", notes: str = "") -> dict:
    """File one completed task. Never raises."""
    tool_failures = list(tool_failures or [])
    ratio = (actual_seconds / predicted_seconds) if predicted_seconds > 0 else 1.0

    lessons: list[str] = []
    if predicted_seconds > 0:
        if ratio >= 2.0:
            lessons.append(
                f"Took {ratio:.1f}x longer than planned "
                f"({actual_seconds:.1f}s vs {predicted_seconds:.1f}s estimated).")
        elif ratio <= 0.5:
            lessons.append(
                f"Finished in {ratio:.1f}x the planned time — the estimate was "
                f"pessimistic.")
    if tool_failures:
        lessons.append(
            "Tool(s) failed: " + ", ".join(sorted(set(tool_failures))) +
            ". A plan depending on these should be marked blocked before it runs.")
    if achieved and confidence < 0.4:
        lessons.append(
            "Succeeded despite low confidence — the planner is under-rating "
            "this kind of goal.")
    if not achieved and confidence > 0.75:
        lessons.append(
            "Failed while highly confident. This is the expensive kind of "
            "error: it is acted on without review.")

    rec = {
        "id": f"refl-{len(_records) + 1:05d}",
        "ts": time.time(),
        "goal": (goal or "")[:200],
        "achieved": bool(achieved),
        "predicted_seconds": round(float(predicted_seconds), 2),
        "actual_seconds": round(float(actual_seconds), 2),
        "ratio": round(ratio, 3),
        "confidence": round(float(confidence), 3),
        "tool_failures": tool_failures,
        "provider": provider,
        "notes": notes[:300],
        "lessons": lessons,
    }

    with _lock:
        _records.append(rec)
        if len(_records) > MAX_HISTORY:
            del _records[:len(_records) - MAX_HISTORY]

    events.emit(events.REFLECTION_RECORDED, {
        "goal": rec["goal"], "achieved": achieved,
        "ratio": rec["ratio"], "lessons": len(lessons),
    }, actor="reflection", severity="info" if achieved else "warn")
    return rec


def calibration() -> float:
    """Multiplier the planner should apply to its raw runtime estimate.

    1.0 means "no correction yet" — either there is not enough evidence, or the
    estimates are already good. Returning 1.0 rather than None keeps the caller
    free of special cases.
    """
    with _lock:
        ratios = [r["ratio"] for r in _records if r["predicted_seconds"] > 0]
    if len(ratios) < MIN_SAMPLES:
        return 1.0
    # Median, not mean: a single timeout would otherwise poison every estimate.
    factor = statistics.median(ratios)
    return round(max(CALIBRATION_FLOOR, min(CALIBRATION_CEIL, factor)), 3)


def _brier(records: list) -> Optional[float]:
    """Mean squared error between stated confidence and what happened.

    0 is perfect, 0.25 is what you get by always saying 50%, 1 is confidently
    wrong every time. It is the honest way to grade a confidence number,
    because it punishes being certain and wrong far more than being unsure.
    """
    scored = [(r["confidence"], 1.0 if r["achieved"] else 0.0) for r in records]
    if not scored:
        return None
    return round(sum((c - o) ** 2 for c, o in scored) / len(scored), 4)


def report(limit: int = 20) -> dict:
    """What reflection has learned, and what it is doing with it."""
    with _lock:
        rows = list(_records)

    total = len(rows)
    achieved = sum(1 for r in rows if r["achieved"])
    ratios = [r["ratio"] for r in rows if r["predicted_seconds"] > 0]
    failing_tools: dict[str, int] = {}
    for r in rows:
        for t in r["tool_failures"]:
            failing_tools[t] = failing_tools.get(t, 0) + 1

    factor = calibration()
    if total < MIN_SAMPLES:
        verdict = (f"Not enough evidence yet — {total} of {MIN_SAMPLES} tasks "
                   f"recorded. Estimates are used uncorrected until then.")
    elif 0.8 <= factor <= 1.25:
        verdict = "Estimates are close to reality; no correction worth applying."
    elif factor > 1.25:
        verdict = (f"Work consistently takes ~{factor}x the estimate. Future "
                   f"plans are inflated by that factor.")
    else:
        verdict = (f"Estimates are pessimistic (~{factor}x). Future plans are "
                   f"shortened accordingly.")

    return {
        "tasks_reflected": total,
        "achieved": achieved,
        "success_rate": round(100.0 * achieved / total, 1) if total else 0.0,
        "median_time_ratio": round(statistics.median(ratios), 3) if ratios else None,
        "calibration_factor": factor,
        "calibration_verdict": verdict,
        "confidence_brier": _brier(rows),
        "confidence_note": (
            "0 is perfect, 0.25 is what always guessing 50% scores, 1 is "
            "confidently wrong every time."),
        "tools_that_failed": dict(sorted(failing_tools.items(),
                                         key=lambda kv: -kv[1])),
        "recent": list(reversed(rows[-limit:])),
        "min_samples_before_correcting": MIN_SAMPLES,
    }


# ------------------------------------------------------------- persistence --
def export_state() -> dict:
    with _lock:
        return {"records": [dict(r) for r in _records]}


def import_state(data: dict) -> None:
    if not isinstance(data, dict):
        return
    rows = data.get("records")
    if not isinstance(rows, list):
        return
    clean = []
    for r in rows[-MAX_HISTORY:]:
        if not isinstance(r, dict):
            continue
        try:
            clean.append({
                "id": str(r.get("id", "")),
                "ts": float(r.get("ts", 0) or 0),
                "goal": str(r.get("goal", ""))[:200],
                "achieved": bool(r.get("achieved")),
                "predicted_seconds": float(r.get("predicted_seconds", 0) or 0),
                "actual_seconds": float(r.get("actual_seconds", 0) or 0),
                "ratio": float(r.get("ratio", 1) or 1),
                "confidence": float(r.get("confidence", 0.5) or 0.5),
                "tool_failures": [str(x) for x in (r.get("tool_failures") or [])
                                  if isinstance(x, (str, int))],
                "provider": str(r.get("provider", "")),
                "notes": str(r.get("notes", ""))[:300],
                "lessons": [str(x) for x in (r.get("lessons") or [])],
            })
        except (TypeError, ValueError):
            continue          # one bad row must not lose the whole history
    with _lock:
        _records.clear()
        _records.extend(clean)


def reset() -> None:
    """Test seam."""
    with _lock:
        _records.clear()
