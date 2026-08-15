"""Tool layer — one interface for every external capability.

Spec Part 2 Layer 4: "Every external capability becomes a Tool. Every Tool
follows one common interface. Never special-case tools."
Spec Part 8: "Never expose third-party projects directly to the rest of the
system. Instead: create internal adapters... allow future replacement without
changing unrelated modules."

Why this exists rather than importing each library where it is needed:

1. **Licence containment.** Firecrawl is AGPL-3.0 and Titan is sold to clients.
   Linking AGPL code into this process would oblige Abdullah to publish Titan's
   source to every user of the hosted Space. Calling a separate Firecrawl
   process over HTTP does not. That distinction is only enforceable if there is
   exactly one place where the call is made — this file's adapters. Each tool
   therefore declares its licence and its integration mode, and
   ``licence_blocked`` tools refuse to run at all.

2. **Honest readiness.** Every one of these needs a key, a URL, or a paid
   account that Abdullah does not yet have. A tool that is not configured
   reports ``not_configured`` and returns a result explaining exactly what is
   missing. Nothing pretends to work, and nothing crashes the caller.

3. **Replaceability.** The rest of Titan asks for a capability
   ("crawl this page"), never for a vendor. Swapping Firecrawl for something
   else later is a change in this file only.

No tool here performs an irreversible or outbound action without an explicit
per-call opt-in — sending WhatsApp messages, placing calls and publishing are
all gated, per spec Part 6 ("Require explicit user approval before: ...
Publishing Content, ... Sending Communications on the user's behalf").
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from . import events

# --------------------------------------------------------------- licensing --
# Measured from the GitHub API on 2026-08-05, not assumed.
#
# EMBED   — code may be vendored into Titan (permissive licence).
# WRAP    — may only be called as a separate process/service over a network API.
#           Embedding would impose the upstream copyleft on Titan itself.
# REFER   — documentation/list only; content may be read by a human but not
#           redistributed. No licence grant to copy.
# BLOCKED — licence unclear. No integration until upstream clarifies.
EMBED, WRAP, REFER, BLOCKED = "embed", "wrap", "refer", "blocked"


@dataclass(frozen=True)
class Provenance:
    repo: str
    licence: str
    mode: str
    note: str = ""


PROVENANCE = {
    "firecrawl": Provenance(
        "firecrawl/firecrawl", "AGPL-3.0", WRAP,
        "AGPL copyleft. Titan is commercial, so this may only ever be called "
        "over HTTP against a separate instance (self-hosted or their cloud). "
        "Vendoring any of its source would oblige Titan to publish its own."),
    "praisonai": Provenance(
        "MervinPraison/PraisonAI", "MIT", EMBED,
        "Permissive. Multi-agent orchestration patterns may be adapted with "
        "attribution."),
    "livekit": Provenance(
        "livekit/agents", "Apache-2.0", EMBED,
        "Permissive; requires NOTICE attribution. Realtime voice transport."),
    "openjarvis": Provenance(
        "open-jarvis/OpenJarvis", "Apache-2.0", EMBED,
        "Permissive; requires NOTICE attribution."),
    "openwa": Provenance(
        "rmyndharis/OpenWA", "MIT", EMBED,
        "Permissive. NOTE: unofficial WhatsApp automation risks account bans — "
        "gated behind explicit approval, never auto-send."),
    "voicebox": Provenance("jamiepine/voicebox", "MIT", EMBED, "Permissive."),
    "floci": Provenance("floci-io/floci", "MIT", EMBED, "Permissive."),
    "compai_crm": Provenance("trycompai/crm", "MIT", EMBED, "Permissive."),
    "tencent_memory": Provenance(
        "TencentCloud/TencentDB-Agent-Memory", "NOASSERTION", BLOCKED,
        "GitHub reports no recognised licence. Integrating code with no licence "
        "grant is a legal risk to a product being sold. Blocked until upstream "
        "states terms."),
    "free_for_dev": Provenance(
        "ripienaar/free-for-dev", "none", REFER,
        "No licence file at all — the list may be read, not redistributed."),
    "awesome_selfhosted": Provenance(
        "awesome-selfhosted/awesome-selfhosted", "NOASSERTION", REFER,
        "Curated list, share-alike terms. Reference only."),
}


# -------------------------------------------------------------- tool result --
@dataclass
class ToolResult:
    ok: bool
    tool: str
    data: dict = field(default_factory=dict)
    error: str = ""
    needs: str = ""          # what the operator must supply to make this work
    elapsed_ms: int = 0

    def as_dict(self) -> dict:
        return {"ok": self.ok, "tool": self.tool, "data": self.data,
                "error": self.error, "needs": self.needs,
                "elapsed_ms": self.elapsed_ms}


@dataclass
class Tool:
    """One capability. The interface every adapter implements."""
    name: str
    capability: str                 # what it does, vendor-free
    run: Callable[..., dict]
    provenance_key: str = ""
    env_required: tuple = ()
    package_required: tuple = ()    # optional python packages, checked not imported
    outbound: bool = False          # true => sends/publishes on the user's behalf

    # -- readiness ---------------------------------------------------------
    def provenance(self) -> Optional[Provenance]:
        return PROVENANCE.get(self.provenance_key)

    def licence_blocked(self) -> bool:
        p = self.provenance()
        return bool(p and p.mode == BLOCKED)

    def missing_env(self) -> list:
        return [k for k in self.env_required if not os.getenv(k, "").strip()]

    def missing_packages(self) -> list:
        """Optional packages that are declared but not installed.

        Checked with find_spec rather than a real import: importing a heavy
        agent framework just to render a status page would cost seconds of boot
        time for information we can get for free.
        """
        import importlib.util
        missing = []
        for pkg in self.package_required:
            try:
                if importlib.util.find_spec(pkg) is None:
                    missing.append(pkg)
            except (ImportError, ValueError):
                missing.append(pkg)
        return missing

    def status(self) -> str:
        if self.licence_blocked():
            return "licence_blocked"
        # "ready" has to mean it actually runs. Reporting ready for a tool whose
        # package is absent moves the failure from this screen to the caller.
        if self.missing_env() or self.missing_packages():
            return "not_configured"
        return "ready"

    def describe(self) -> dict:
        p = self.provenance()
        return {
            "name": self.name,
            "capability": self.capability,
            "status": self.status(),
            "outbound": self.outbound,
            "missing_env": self.missing_env(),
            "missing_packages": self.missing_packages(),
            "upstream": p.repo if p else None,
            "licence": p.licence if p else None,
            "integration_mode": p.mode if p else None,
            "licence_note": p.note if p else "",
        }

    # -- invocation --------------------------------------------------------
    def invoke(self, **kwargs) -> ToolResult:
        """Run the tool. Never raises — a failing tool returns a failed result.

        Refuses before doing anything if the licence is unresolved or the
        configuration is missing, so the caller gets a precise reason instead of
        a network error twenty seconds later.
        """
        started = time.monotonic()

        def _finish(res: ToolResult) -> ToolResult:
            res.elapsed_ms = int((time.monotonic() - started) * 1000)
            events.emit(
                events.TOOL_INVOKED if res.ok else events.TOOL_FAILED,
                {"tool": self.name, "ok": res.ok, "error": res.error,
                 "needs": res.needs, "elapsed_ms": res.elapsed_ms},
                actor="tools", severity="info" if res.ok else "warn")
            return res

        if self.licence_blocked():
            p = self.provenance()
            return _finish(ToolResult(
                False, self.name,
                error="Blocked on licence, not on engineering.",
                needs=(p.note if p else "Upstream licence is unresolved.")))

        missing = self.missing_env()
        if missing:
            return _finish(ToolResult(
                False, self.name,
                error="Not configured.",
                needs=f"Set {', '.join(missing)} to enable {self.name}."))

        absent = self.missing_packages()
        if absent:
            return _finish(ToolResult(
                False, self.name,
                error="Dependency not installed.",
                needs=f"pip install {' '.join(absent)} — deliberately not in "
                      f"requirements.txt yet; benchmark it before adopting."))

        if self.outbound and not kwargs.get("approved"):
            # Spec Part 6: never send on the user's behalf without approval.
            return _finish(ToolResult(
                False, self.name,
                error="Refused: this tool acts outside Titan.",
                needs="Pass approved=True after a human has reviewed the exact "
                      "content being sent."))

        try:
            payload = self.run(**kwargs)
        except Exception as exc:
            return _finish(ToolResult(
                False, self.name,
                error=f"{type(exc).__name__}: {str(exc)[:200]}"))

        # An adapter that reports its OWN failure is a failure. This used to
        # treat "did not raise" as success, which is fine while every adapter
        # signals by raising — but the API capabilities do not. A provider
        # being down is a normal outcome for them, not an exception, so they
        # return {"ok": False, "error": ...}. Under the old rule a weather
        # lookup that reached nobody came back as a successful tool run whose
        # data happened to say otherwise, and the failure counters in
        # reflection.py would never have seen it.
        if isinstance(payload, dict) and payload.get("ok") is False:
            return _finish(ToolResult(
                False, self.name, data=payload,
                error=str(payload.get("error")
                          or "The capability reported failure without a reason.")))
        return _finish(ToolResult(True, self.name, data=payload))


# ------------------------------------------------------------------ registry --
_REGISTRY: dict[str, Tool] = {}


def register(tool: Tool) -> Tool:
    _REGISTRY[tool.name] = tool
    return tool


def get(name: str) -> Optional[Tool]:
    return _REGISTRY.get(name)


def all_tools() -> list:
    return [_REGISTRY[k] for k in sorted(_REGISTRY)]


def registry_report() -> dict:
    tools = [t.describe() for t in all_tools()]
    return {
        "tools": tools,
        "ready": sum(1 for t in tools if t["status"] == "ready"),
        "not_configured": sum(1 for t in tools if t["status"] == "not_configured"),
        "licence_blocked": sum(1 for t in tools if t["status"] == "licence_blocked"),
        "note": ("Every capability below is reachable through one interface. "
                 "'not_configured' means a key or URL is missing — that is the "
                 "only thing standing between it and working. 'licence_blocked' "
                 "cannot be unblocked by writing code."),
    }
