"""Self-improvement: observe → propose → measure isolated → Abdullah approves
→ activate → auto-rollback.

**Nothing here ever deploys itself.** That is not a configuration choice, it is
the structure: `activate()` refuses any proposal that is not already `approved`,
and `approve()` refuses without a named human. There is no flag, no "auto" mode
and no scheduled approver, for the same reason `site_fix` has no auto-apply — a
model changing how a live product behaves at 3am, unattended, is how this
product dies. `fix_cycle` proposes and never applies; this is the same shape
pointed at Titan itself.

What it can actually change is narrow and stated plainly in `core/params.py`:
registered numeric parameters, with bounds, that are read as module globals at
call time and have a benchmark. **Titan cannot modify its own source code** —
that needs a git push and a rebuild, and the container has no git credentials.

The measurement discipline is the part that matters:

* A proposal is measured **before** anyone is asked to approve it. `approve()`
  refuses a proposal that has not been evaluated: an approval without numbers
  is a guess with a signature on it.
* The candidate is applied, benchmarked and **restored in a `finally`, and the
  restoration is then VERIFIED**. A scratch mutation script in this repo once
  left `if False:` inside `backup.py` and silently disabled the check that a
  backup restores. Anything that edits live state to measure it has to prove it
  put it back.
* A candidate that measures WORSE cannot be approved at all. It is recorded
  with its numbers, because a measured failure is a result worth keeping.
* `previous_value` is read off the live module at activation, not taken from
  the source default. Rollback restores what was actually running.
* Auto-rollback re-measures and reverts on regression. It is the one automatic
  action here, and it only ever moves a value BACK to something a human already
  approved of — the safe direction.

Numbers are `None` until measured. A proposal that has not been benchmarked
reports `before_metric: None`, never 0.0.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from typing import Any, Optional

from . import events, params

PROPOSED = "proposed"
EVALUATED = "evaluated"
APPROVED = "approved"
ACTIVE = "active"
REJECTED = "rejected"
ROLLED_BACK = "rolled_back"
SUPERSEDED = "superseded"

OPEN_STATUSES = (PROPOSED, EVALUATED, APPROVED, ACTIVE)

_lock = threading.RLock()


def _conn():
    from .. import persistence
    from . import db
    return db.connect(persistence.STATE_FILE)


def _row(r) -> dict:
    out = dict(r)
    out["evidence"] = json.loads(out.get("evidence") or "{}")
    out["regression"] = (None if out.get("regression") is None
                         else bool(out["regression"]))
    out["automatic_rollback"] = bool(out.get("automatic_rollback"))
    # None until measured, like before_metric — never an empty "all clear".
    raw = out.get("guard_metrics")
    out["guard_metrics"] = json.loads(raw) if raw else None
    return out


def _worse(now, then, higher_is_better: bool) -> bool:
    return now < then if higher_is_better else now > then


def get(proposal_id: str) -> Optional[dict]:
    cur = _conn().execute("SELECT * FROM proposals WHERE id = ?", (proposal_id,))
    row = cur.fetchone()
    return _row(row) if row else None


def listing(status: str = "", limit: int = 50) -> list:
    sql = "SELECT * FROM proposals"
    args: list = []
    if status:
        sql += " WHERE status = ?"
        args.append(status)
    sql += " ORDER BY created_at DESC LIMIT ?"
    args.append(int(limit))
    return [_row(r) for r in _conn().execute(sql, args).fetchall()]


# --- observe ----------------------------------------------------------------
def observe() -> dict:
    """Real signals only, each labelled with where it came from.

    This does not propose anything. It reports what is measurable right now, so
    a proposal can cite something rather than assert an improvement.
    """
    signals: list[dict] = []

    try:
        from . import reflection
        rep = reflection.report(limit=50)
        signals.append({
            "source": "reflection.report",
            "samples": rep.get("samples"),
            "calibration": rep.get("calibration"),
            "brier": rep.get("brier"),
            # None, not 0 — below MIN_SAMPLES there is nothing to say.
            "note": "planner estimate bias; None until enough samples exist",
        })
    except Exception as exc:
        signals.append({"source": "reflection.report", "error": str(exc)[:120]})

    for name in sorted(params.PARAMS):
        param = params.PARAMS[name]
        try:
            value = params.current(name)
        except Exception:
            value = None
        signals.append({
            "source": "params.current",
            "param": name,
            "value": value,
            "benchmark": param.benchmark,
            "why_default": param.why_default,
        })

    return {
        "signals": signals,
        "observed_at": time.time(),
        "note": ("Observations, not conclusions. Nothing here proposes a "
                 "change; a proposal has to be measured before it can be "
                 "approved."),
    }


# --- propose ----------------------------------------------------------------
def propose(param: str, value: Any, *, reason: str,
            evidence: Optional[dict] = None) -> dict:
    """Record a candidate. Measures nothing and changes nothing."""
    if param not in params.PARAMS:
        raise ValueError(
            f"{param!r} is not a registered parameter. Only the entries in "
            f"core/params.py can be changed: {sorted(params.PARAMS)}")
    if not (reason or "").strip():
        raise ValueError("A proposal must say why. An unexplained change to "
                         "Titan's own behaviour is not reviewable.")

    spec = params.PARAMS[param]
    cast = params.coerce(spec, value)          # raises outside bounds
    baseline = params.current(param)
    if cast == baseline:
        raise ValueError(f"{param} is already {baseline}.")

    row = {
        "id": uuid.uuid4().hex[:12],
        "param": param,
        "proposed_value": cast,
        "baseline_value": float(baseline),
        "previous_value": None,
        "status": PROPOSED,
        "reason": reason.strip(),
        "evidence": json.dumps(evidence or {}),
        "benchmark": spec.benchmark,
        "metric": spec.metric,
        "before_metric": None,
        "after_metric": None,
        "regression": None,
        "guard_metrics": None,
        "approver": None,
        "decided_at": None,
        "activated_at": None,
        "rolled_back_at": None,
        "rollback_reason": None,
        "automatic_rollback": 0,
        "created_at": time.time(),
    }
    with _lock:
        conn = _conn()
        with conn:
            conn.execute(
                "INSERT INTO proposals ({}) VALUES ({})".format(
                    ", ".join(row), ", ".join("?" * len(row))),
                list(row.values()))
    events.emit("improvement.proposed",
                {"id": row["id"], "param": param, "from": baseline,
                 "to": cast, "reason": row["reason"]},
                actor="improve", severity="info")
    return get(row["id"])


# --- measure ----------------------------------------------------------------
def _measure(param_name: str, value: Any) -> dict:
    """Run the parameter's benchmark with `value` applied, then put it back.

    The restoration is verified. Measuring by mutating live state and failing
    to restore it would leave Titan running a value nobody approved, which is
    the exact failure this module exists to make impossible.
    """
    spec = params.PARAMS[param_name]
    bench = params.benchmark(spec.benchmark)
    if bench is None:
        raise RuntimeError(
            f"No benchmark registered as {spec.benchmark!r}; a change that "
            f"cannot be measured cannot be proposed.")

    module = params._module(spec)
    original = getattr(module, spec.attr)
    try:
        setattr(module, spec.attr, params.coerce(spec, value))
        result = bench()
    finally:
        setattr(module, spec.attr, original)
        restored = getattr(module, spec.attr)
        if restored != original:
            raise RuntimeError(
                f"FATAL: {spec.module}.{spec.attr} was not restored after "
                f"measurement ({restored!r}, expected {original!r}).")
    missing = [m for m in (spec.metric, *(g for g, _ in spec.guards))
               if m not in result]
    if missing:
        raise RuntimeError(
            f"Benchmark {spec.benchmark!r} reported no {missing}; "
            f"got {sorted(result)}.")
    return result


def evaluate(proposal_id: str) -> dict:
    """Measure baseline and candidate. Never changes what is running."""
    row = get(proposal_id)
    if row is None:
        raise ValueError(f"No such proposal: {proposal_id}")
    if row["status"] != PROPOSED:
        raise ValueError(
            f"Only a {PROPOSED} proposal can be evaluated; this one is "
            f"{row['status']}.")

    spec = params.PARAMS[row["param"]]
    base = _measure(row["param"], row["baseline_value"])
    cand = _measure(row["param"], row["proposed_value"])
    before, after = base[spec.metric], cand[spec.metric]

    # Equal is NOT an improvement. A change that measures identically is churn
    # on a live product, and churn is a risk with no upside.
    if spec.higher_is_better:
        regression = after <= before
    else:
        regression = after >= before
    # Nor is one bought with another number the same benchmark measures:
    # fewer silent answers paid for in invented ones is a worse receptionist.
    guards = {m: {"before": base[m], "after": cand[m],
                  "worse": _worse(cand[m], base[m], hib)}
              for m, hib in spec.guards}
    broken = [m for m, g in guards.items() if g["worse"]]
    regression = regression or bool(broken)

    with _lock:
        conn = _conn()
        with conn:
            conn.execute(
                "UPDATE proposals SET status = ?, before_metric = ?, "
                "after_metric = ?, regression = ?, guard_metrics = ? "
                "WHERE id = ?",
                (EVALUATED, float(before), float(after),
                 1 if regression else 0, json.dumps(guards), proposal_id))
    events.emit("improvement.evaluated",
                {"id": proposal_id, "param": row["param"],
                 "metric": spec.metric, "before": before, "after": after,
                 "regression": regression, "guards_broken": broken},
                actor="improve",
                severity="info" if not regression else "warn")
    return get(proposal_id)


# --- decide -----------------------------------------------------------------
def approve(proposal_id: str, approver: str) -> dict:
    """A named human accepts a MEASURED change. Nothing else may call this."""
    if not (approver or "").strip():
        raise ValueError("Approval must carry a name. An anonymous approval is "
                         "not an audit trail.")
    row = get(proposal_id)
    if row is None:
        raise ValueError(f"No such proposal: {proposal_id}")
    if row["status"] != EVALUATED:
        raise ValueError(
            f"Only an {EVALUATED} proposal can be approved; this one is "
            f"{row['status']}. Approving an unmeasured change is a guess with "
            f"a signature on it.")
    if row["regression"]:
        broken = [f"{m} went {g['before']} → {g['after']}"
                  for m, g in (row["guard_metrics"] or {}).items() if g["worse"]]
        raise ValueError(
            f"This measured WORSE: {row['metric']} went "
            f"{row['before_metric']} → {row['after_metric']}"
            + (f", and {'; '.join(broken)}" if broken else "")
            + ". It cannot be approved.")

    with _lock:
        conn = _conn()
        with conn:
            conn.execute(
                "UPDATE proposals SET status = ?, approver = ?, decided_at = ? "
                "WHERE id = ?",
                (APPROVED, approver.strip(), time.time(), proposal_id))
    events.emit("improvement.approved",
                {"id": proposal_id, "param": row["param"],
                 "approver": approver.strip()},
                actor="improve", severity="info")
    return get(proposal_id)


def reject(proposal_id: str, approver: str, why: str = "") -> dict:
    row = get(proposal_id)
    if row is None:
        raise ValueError(f"No such proposal: {proposal_id}")
    if row["status"] not in (PROPOSED, EVALUATED):
        raise ValueError(f"Cannot reject a {row['status']} proposal.")
    with _lock:
        conn = _conn()
        with conn:
            conn.execute(
                "UPDATE proposals SET status = ?, approver = ?, decided_at = ?, "
                "rollback_reason = ? WHERE id = ?",
                (REJECTED, (approver or "").strip(), time.time(),
                 (why or "").strip() or None, proposal_id))
    return get(proposal_id)


# --- activate and roll back -------------------------------------------------
def activate(proposal_id: str) -> dict:
    """Apply an APPROVED proposal. The gate that makes this not self-deploying."""
    row = get(proposal_id)
    if row is None:
        raise ValueError(f"No such proposal: {proposal_id}")
    if row["status"] != APPROVED:
        raise ValueError(
            f"Only an {APPROVED} proposal can be activated; this one is "
            f"{row['status']}. Titan does not deploy its own changes.")

    # Read off the LIVE module. The shipped default is not necessarily what is
    # running, and rollback has to restore what actually was.
    previous = float(params.current(row["param"]))
    applied = params.set_value(row["param"], row["proposed_value"])

    with _lock:
        conn = _conn()
        with conn:
            conn.execute(
                "UPDATE proposals SET status = ?, previous_value = ?, "
                "activated_at = ? WHERE id = ?",
                (ACTIVE, previous, time.time(), proposal_id))
    events.emit("improvement.activated",
                {"id": proposal_id, "param": row["param"],
                 "from": previous, "to": applied,
                 "approver": row["approver"]},
                actor="improve", severity="warn")
    return get(proposal_id)


def rollback(proposal_id: str, *, why: str, automatic: bool = False) -> dict:
    """Restore the exact value that was running before activation."""
    row = get(proposal_id)
    if row is None:
        raise ValueError(f"No such proposal: {proposal_id}")
    if row["status"] != ACTIVE:
        raise ValueError(f"Only an {ACTIVE} proposal can be rolled back; this "
                         f"one is {row['status']}.")
    if row["previous_value"] is None:
        raise ValueError(
            "No previous value was snapshotted, so this cannot be rolled back "
            "to a known state. Set the parameter by hand.")

    params.set_value(row["param"], row["previous_value"])

    with _lock:
        conn = _conn()
        with conn:
            conn.execute(
                "UPDATE proposals SET status = ?, rolled_back_at = ?, "
                "rollback_reason = ?, automatic_rollback = ? WHERE id = ?",
                (ROLLED_BACK, time.time(), (why or "").strip(),
                 1 if automatic else 0, proposal_id))
    events.emit("improvement.rolled_back",
                {"id": proposal_id, "param": row["param"],
                 "restored": row["previous_value"], "why": why,
                 "automatic": automatic},
                actor="improve", severity="warn")
    return get(proposal_id)


def check_active() -> list:
    """Re-measure every ACTIVE change and roll back any that got worse.

    The only automatic action in this module, and it only ever moves a value
    BACK to one that was already running before a human approved a change —
    the safe direction. It never approves, activates or proposes.
    """
    out = []
    for row in listing(status=ACTIVE, limit=20):
        spec = params.PARAMS.get(row["param"])
        if spec is None or row["before_metric"] is None:
            continue
        try:
            result = _measure(row["param"], row["proposed_value"])
        except Exception as exc:
            out.append({"id": row["id"], "param": row["param"],
                        "error": str(exc)[:160]})
            continue

        now = result[spec.metric]
        stored = row["guard_metrics"] or {}   # none for pre-guard proposals
        broken = [f"{m} measured {result[m]} against {stored[m]['before']}"
                  for m, hib in spec.guards
                  if m in stored and _worse(result[m], stored[m]["before"], hib)]
        worse = _worse(now, row["before_metric"], spec.higher_is_better) or bool(broken)
        entry = {"id": row["id"], "param": row["param"],
                 "metric": spec.metric, "baseline": row["before_metric"],
                 "now": now, "guards_broken": broken, "rolled_back": False}
        if worse:
            rollback(row["id"],
                     why=(f"Automatic: {spec.metric} measured {now} against an "
                          f"approved baseline of {row['before_metric']}"
                          + (f"; {'; '.join(broken)}" if broken else "") + "."),
                     automatic=True)
            entry["rolled_back"] = True
        out.append(entry)
    return out


def report() -> dict:
    rows = listing(limit=100)
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return {
        "proposals": rows,
        "counts": counts,
        "awaiting_approval": counts.get(EVALUATED, 0),
        "active": counts.get(ACTIVE, 0),
        "note": ("Titan never activates its own proposals. `approve` requires "
                 "a named human and refuses anything unmeasured or measured "
                 "worse; `activate` refuses anything not already approved. "
                 "Only rollback is automatic."),
    }
