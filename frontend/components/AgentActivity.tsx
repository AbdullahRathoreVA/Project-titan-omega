"use client";

import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Cpu } from "lucide-react";
import type { AgentView } from "@/lib/types";
import { timeAgo } from "@/lib/format";
import { AgentDetailModal } from "./AgentDetailModal";

const STATUS_DOT: Record<string, string> = {
  working: "bg-hud-emerald shadow-glow-emerald",
  idle: "bg-slate-500",
  blocked: "bg-hud-rose",
  offline: "bg-slate-700",
};

export function AgentActivity({ agents }: { agents: AgentView[] }) {
  const [selected, setSelected] = useState<AgentView | null>(null);

  const sorted = [...agents]
    .sort((a, b) => b.impact_score - a.impact_score)
    .slice(0, 14);

  return (
    <>
      <AgentDetailModal agent={selected} onClose={() => setSelected(null)} />
      <section className="panel flex h-full flex-col">
        <header className="panel-header">
          <div className="flex items-center gap-2">
            <Cpu className="h-4 w-4 text-hud-violet" strokeWidth={1.6} />
            <h2 className="text-sm font-medium text-slate-200">Agent Activity</h2>
          </div>
          <span className="hud-label">{agents.length} employees · click to inspect</span>
        </header>
        <div className="scroll-thin flex-1 space-y-1.5 overflow-y-auto p-2">
          {sorted.map((a, i) => (
            <motion.div
              key={a.id}
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ delay: i * 0.02 }}
              onClick={() => setSelected(a)}
              className="flex cursor-pointer items-center gap-2.5 rounded-lg border border-edge/60 bg-panel-2/40 px-2.5 py-2 transition-colors hover:border-hud-violet/30 hover:bg-panel-2/80"
            >
              <span
                className={`h-2 w-2 shrink-0 rounded-full ${STATUS_DOT[a.status] ?? "bg-slate-600"} ${
                  a.status === "working" ? "animate-pulse" : ""
                }`}
              />
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-1.5">
                  <span className="truncate text-xs text-slate-200">{a.name}</span>
                  {a.is_head && (
                    <span className="rounded bg-hud-violet/15 px-1 text-[9px] font-medium uppercase text-hud-violet">
                      head
                    </span>
                  )}
                </div>
                {/* Live task line — fades/slides each time the agent advances a stage */}
                <div className="relative h-[13px] overflow-hidden">
                  <AnimatePresence mode="wait">
                    <motion.div
                      key={a.current_task ?? a.mission}
                      initial={{ opacity: 0, y: 7 }}
                      animate={{ opacity: 1, y: 0 }}
                      exit={{ opacity: 0, y: -7 }}
                      transition={{ duration: 0.28 }}
                      className="truncate text-[10px] text-slate-500"
                    >
                      {a.status === "working" && (
                        <span className="mr-1 text-hud-emerald">▸</span>
                      )}
                      {a.current_task ?? a.mission}
                    </motion.div>
                  </AnimatePresence>
                </div>
                {/* Workflow progress through the division pipeline */}
                {a.status === "working" && typeof a.progress === "number" && (
                  <div className="mt-1 h-[2px] w-full overflow-hidden rounded-full bg-panel-2">
                    <motion.div
                      className="h-full rounded-full bg-gradient-to-r from-hud-cyan to-hud-violet"
                      animate={{ width: `${Math.round((a.progress || 0) * 100)}%` }}
                      transition={{ duration: 0.5, ease: "easeOut" }}
                    />
                  </div>
                )}
              </div>
              <div className="shrink-0 text-right">
                <div className="font-mono text-[11px] text-hud-cyan">
                  {a.impact_score.toFixed(0)}
                </div>
                <div className="text-[9px] text-slate-600">{timeAgo(a.last_active)}</div>
              </div>
            </motion.div>
          ))}
        </div>
      </section>
    </>
  );
}
