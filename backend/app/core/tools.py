"""Tool layer: one interface for every external capability.

Every external capability is a Tool with the same interface, and third-party
projects are only reached through these adapters, so they can be replaced
without touching the rest of the system.

1. Licence containment. Firecrawl is AGPL-3.0 and Titan is a commercial
   service. Linking AGPL code into this process would mean publishing Titan's
   source to every user of the hosted Space; calling a separate Firecrawl
   process over HTTP doesn't. That only holds if there's exactly one place
   the call is made, so each tool declares its licence and integration mode,
   and ``licence_blocked`` tools refuse to run.
2. Clear readiness. Most of these need a key, a URL or a paid account. A tool
   that isn't configured reports ``not_configured`` and a result saying
   exactly what's missing, instead of crashing the caller.
3. Replaceability. The rest of Titan asks for a capability ("crawl this
   page"), never a vendor, so swapping one is a change in this file only.

No tool does anything irreversible or outbound (sending WhatsApp messages,
placing calls, publishing) without an explicit per-call opt-in from the user.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from . import events

# --------------------------------------------------------------- licensing --
# Checked against the GitHub API on 2026-08-05.
#
# EMBED   - code may be vendored into Titan (permissive licence).
# WRAP    - may only be called as a separate process/service over a network API;
#           embedding would put the upstream copyleft on Titan.
# REFER   - documentation/list only; can be read but not redistributed.
# BLOCKED - licence unclear. No integration until upstream clarifies.
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

        Checked with find_spec rather than importing: importing a heavy framework
        just for a status page would add seconds to boot.
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
        # "ready" has to mean it actually runs; otherwise the failure just moves from
        # this screen to the caller.
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
        """Run the tool. Never raises - a failing tool returns a failed result.

        Refuses up front if the licence is unresolved or configuration is missing,
        so the caller gets a precise reason instead of a network error later.
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
            # Never send on the user's behalf without approval.
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

        # An adapter that reports its own failure is a failure. API capabilities
        # treat a provider being down as a normal outcome and return
        # {"ok": False, "error": ...} instead of raising; counting that as success
        # would hide it from the failure counters in reflection.py.
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
