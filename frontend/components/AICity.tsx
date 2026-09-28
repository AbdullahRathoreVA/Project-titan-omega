"use client";

// AI City view: a full-canvas 3D city of the divisions. Click a district and the
// camera flies there while its agents panel slides in; click an agent to inspect
// and talk to it. ESC / Back flies the camera home.

import { Component, useEffect, useState, type ReactNode } from "react";
import dynamic from "next/dynamic";
import { motion, AnimatePresence } from "framer-motion";
import { ArrowLeft, Building2 } from "lucide-react";
import type { AgentView, DivisionView } from "@/lib/types";
import { AgentDetailModal } from "./AgentDetailModal";
import { tap } from "@/lib/sound";

const City3D = dynamic(() => import("./AICity3D"), {
  ssr: false,
  loading: () => (
    <div className="flex h-full items-center justify-center font-mono text-xs text-hud-cyan animate-pulseGlow">
      Materializing the city…
    </div>
  ),
});

class Boundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    return this.state.failed ? (
      <div className="flex h-full items-center justify-center text-xs text-slate-500">
        3D unavailable on this device — the rest of Titan still works.
      </div>
    ) : (
      this.props.children
    );
  }
}

const STATUS_DOT: Record<string, string> = {
  working: "bg-hud-emerald",
  idle: "bg-slate-500",
  blocked: "bg-hud-rose",
  offline: "bg-slate-700",
};

export function AICity({
  divisions,
  agents,
  intensity,
}: {
  divisions: DivisionView[];
  agents: AgentView[];
  intensity: number;
}) {
  const [selected, setSelected] = useState<string | null>(null);
  const [agentSel, setAgentSel] = useState<AgentView | null>(null);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") setSelected(null);
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, []);

  const division = divisions.find((d) => d.division === selected) ?? null;
  const districtAgents = selected
    ? agents.filter((a) => a.division === selected).sort((a, b) => b.impact_score - a.impact_score)
    : [];

  return (
    <div className="panel relative h-[72vh] min-h-[500px] overflow-hidden">
      <AgentDetailModal agent={agentSel} onClose={() => setAgentSel(null)} />

      <div className="absolute inset-0">
        <Boundary>
          <City3D
            divisions={divisions}
            selected={selected}
            onSelect={(d) => {
              tap();
              setSelected(d);
            }}
            intensity={intensity}
          />
        </Boundary>
      </div>

      <div className="pointer-events-none absolute left-4 top-3 z-10">
        <div className="hud-label">AI City · {divisions.length} districts</div>
        <div className="mt-0.5 text-[10px] text-slate-600">
          click a district — the camera flies there
        </div>
      </div>

      <AnimatePresence>
        {division && (
          <motion.aside
            initial={{ x: 340, opacity: 0 }}
            animate={{ x: 0, opacity: 1 }}
            exit={{ x: 340, opacity: 0 }}
            transition={{ type: "spring", stiffness: 260, damping: 28 }}
            className="absolute right-3 top-3 bottom-3 z-10 w-[300px] rounded-xl border border-edge bg-panel/90 backdrop-blur-md"
          >
            <div className="flex items-center justify-between border-b border-edge/60 px-3 py-2.5">
              <div className="flex items-center gap-2">
                <Building2 className="h-4 w-4 text-hud-cyan" />
                <span className="text-xs font-semibold uppercase tracking-wide text-slate-200">
                  {division.division} district
                </span>
              </div>
              <button
                onClick={() => setSelected(null)}
                className="flex items-center gap-1 rounded border border-edge px-2 py-1 text-[10px] text-slate-400 hover:border-hud-cyan/40 hover:text-hud-cyan"
              >
                <ArrowLeft className="h-3 w-3" /> city
              </button>
            </div>
            <div className="px-3 py-2 text-[10px] text-slate-500">
              Head: <span className="text-slate-300">{division.head}</span> · health{" "}
              <span className="text-hud-emerald">{division.health.toFixed(0)}</span> ·{" "}
              {division.active_agents}/{division.agent_count} active
            </div>
            <div className="scroll-thin h-[calc(100%-88px)] space-y-1.5 overflow-y-auto px-3 pb-3">
              {districtAgents.map((a) => (
                <button
                  key={a.id}
                  onClick={() => setAgentSel(a)}
                  className="flex w-full items-center gap-2.5 rounded-lg border border-edge/60 bg-panel-2/50 px-2.5 py-2 text-left transition-colors hover:border-hud-cyan/30"
                >
                  <span className={`h-2 w-2 shrink-0 rounded-full ${STATUS_DOT[a.status] ?? "bg-slate-600"}`} />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-xs text-slate-200">{a.name}</div>
                    <div className="truncate text-[10px] text-slate-500">{a.current_task ?? a.mission}</div>
                  </div>
                  <span className="font-mono text-[10px] text-hud-cyan">{a.impact_score.toFixed(0)}</span>
                </button>
              ))}
            </div>
          </motion.aside>
        )}
      </AnimatePresence>
    </div>
  );
}
