"""Find capabilities that are defined, tested, and called by nothing.

This repository's dominant defect class, found EIGHT times and every single
time by accident:

    knowledge.backfill()          shipped, unit-tested, endpoint exposed, and
                                  the semantic ranker was dead code in prod
    params.apply_stored()         same shape
    improve.check_active()        auto-rollback that never ran
    core/identity.py              an entire module, the login, uncalled
    clients.SESSION_TTL           a constant with a reason and no comparison
    ratelimit.LIMITS["demo"]      a limit that limited nothing
    ratelimit.LIMITS["discover"]  same
    GET /api/client/social        served, and the page hardcoded its own answer

Every one of those read, in the source, exactly like working code. Tests
passed. Documentation described them. Nothing invoked them.

Finding the ninth by luck is not a strategy. This walks the AST of app/** and
reports every public module-level function with no call site anywhere in the
application — excluding the ways a function can legitimately be reached without
a literal call, each of which is listed and justified below rather than being
silently skipped.

Run:  python -m evaluation.dead_code
      python -m evaluation.dead_code --json
"""

from __future__ import annotations

import ast
import io
import json
import os
import sys
from collections import defaultdict

APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "app")

# Ways a function is genuinely reached without a literal `name(...)` in app/**.
# Each entry is a REASON, not a mute button: if you add one, say why the caller
# cannot be seen by a static walk.
EXEMPT_DECORATORS = {
    # FastAPI calls these. The route decorator IS the call site.
    "router.get", "router.post", "router.put", "router.patch", "router.delete",
    "app.get", "app.post", "app.put", "app.patch", "app.delete",
    "app.middleware", "app.on_event", "app.exception_handler",
    "asynccontextmanager", "contextmanager", "property", "staticmethod",
    "classmethod", "dataclass", "lru_cache", "cache",
}

# Names whose caller is the language, the framework, or a test harness.
EXEMPT_NAMES = {
    "main", "lifespan", "seed", "register_all",
    # Test-isolation hooks. Their caller IS the test suite, by design: module
    # level state has to be resettable between tests or one test poisons the
    # next. Listing them is not a mute button — a reset() with no test calling
    # it is dead, but that is the suite's problem to notice, not this tool's.
    "reset",
}

# Prefixes that mark a deliberate public API surface consumed from OUTSIDE the
# application process: adapters registered by string, engine entry points the
# heartbeat resolves dynamically, and the tool registry.
DYNAMIC_HINTS = ("handler_", "adapter_", "tool_", "cmd_")


def _module_name(path: str) -> str:
    rel = os.path.relpath(path, os.path.dirname(APP))
    return rel.replace(os.sep, ".")[: -len(".py")]


def _decorator_name(node: ast.expr) -> str:
    if isinstance(node, ast.Call):
        return _decorator_name(node.func)
    if isinstance(node, ast.Attribute):
        return f"{_decorator_name(node.value)}.{node.attr}"
    if isinstance(node, ast.Name):
        return node.id
    return ""


def collect() -> dict:
    """Every public module-level def in app/**, and every name ever called."""
    defined: dict[str, dict] = {}
    called: set[str] = set()
    attribute_uses: set[str] = set()
    string_literals: set[str] = set()

    for root, _dirs, files in os.walk(APP):
        if "__pycache__" in root:
            continue
        for fname in sorted(files):
            if not fname.endswith(".py"):
                continue
            path = os.path.join(root, fname)
            try:
                tree = ast.parse(io.open(path, encoding="utf-8").read(),
                                 filename=path)
            except SyntaxError as exc:                        # pragma: no cover
                print(f"SKIP (unparseable) {path}: {exc}")
                continue

            module = _module_name(path)

            for node in tree.body:
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if node.name.startswith("_"):
                    continue
                decorators = {_decorator_name(d) for d in node.decorator_list}
                if decorators & EXEMPT_DECORATORS:
                    continue
                if node.name in EXEMPT_NAMES:
                    continue
                if any(node.name.startswith(p) for p in DYNAMIC_HINTS):
                    continue
                defined[f"{module}.{node.name}"] = {
                    "module": module, "name": node.name,
                    "file": os.path.relpath(path, os.path.dirname(APP)),
                    "line": node.lineno,
                }

            # Every call, attribute access and string literal ANYWHERE in the
            # app. Attribute access counts because `mod.fn` passed as a value
            # (a handler, a callback, a monkeypatch target) is a real caller.
            # String literals count because a registry keyed by name is a real
            # caller too, and pretending otherwise produces false alarms that
            # teach people to ignore this tool.
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    fn = node.func
                    if isinstance(fn, ast.Name):
                        called.add(fn.id)
                    elif isinstance(fn, ast.Attribute):
                        called.add(fn.attr)
                elif isinstance(node, ast.Attribute):
                    attribute_uses.add(node.attr)
                elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                    # A bare name READ is a real reference. This tool's first
                    # version missed it and reported fix_cycle.audit_and_propose
                    # as uncalled, when it is handed to queue.register() as a
                    # value one line below its own definition. A dead-code
                    # detector that cries wolf is worse than none: it trains
                    # people to skim its output.
                    attribute_uses.add(node.id)
                elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                    string_literals.add(node.value)

    return {"defined": defined, "called": called,
            "attribute_uses": attribute_uses, "strings": string_literals}


def uncalled() -> list[dict]:
    data = collect()
    out = []
    for qual, info in sorted(data["defined"].items()):
        name = info["name"]
        if name in data["called"]:
            continue
        if name in data["attribute_uses"]:
            continue
        if name in data["strings"]:
            continue
        out.append(info | {"qualified": qual})
    return out


def report() -> dict:
    rows = uncalled()
    by_module = defaultdict(list)
    for row in rows:
        by_module[row["module"]].append(row)
    return {
        "uncalled": rows,
        "count": len(rows),
        "modules": {m: len(v) for m, v in sorted(by_module.items())},
        "note": ("A name here is DEFINED in app/** and never called, accessed "
                 "as an attribute, or named in a string literal anywhere in "
                 "app/**. That does not prove it is dead — it proves nothing "
                 "in the application reaches it, which is exactly the state "
                 "knowledge.backfill() was in while its tests passed."),
    }


if __name__ == "__main__":
    data = report()
    if "--json" in sys.argv:
        print(json.dumps(data, indent=2))
        sys.exit(0)
    print(f"{data['count']} public function(s) in app/** with no caller in app/**\n")
    for row in data["uncalled"]:
        print(f"  {row['file']}:{row['line']}  {row['name']}()")
    print()
    print(data["note"])
