"use client";

import { useEffect, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { X, Target, Wrench, Zap, CheckCircle, TrendingUp } from "lucide-react";
import type { AgentView } from "@/lib/types";
import { timeAgo } from "@/lib/format";

const STATUS_COLOR: Record<string, string> = {
  working: "text-hud-emerald",
  idle: "text-slate-400",
  blocked: "text-hud-rose",
  offline: "text-slate-600",
};

const STATUS_DOT: Record<string, string> = {
  working: "bg-hud-emerald",
  idle: "bg-slate-500",
  blocked: "bg-hud-rose",
  offline: "bg-slate-700",
};

interface Props {
  agent: AgentView | null;
  onClose: () => void;
}

export function AgentDetailModal({ agent, onClose }: Props) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [onClose]);

  return (
    <AnimatePresence>
      {agent && (
        <>
          {/* Backdrop */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
            className="fixed inset-0 z-40 bg-black/60 backdrop-blur-sm"
          />
          {/* Modal */}
          <motion.div
            ref={ref}
            initial={{ opacity: 0, scale: 0.95, y: 20 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 20 }}
            transition={{ type: "spring", stiffness: 300, damping: 25 }}
            className="fixed inset-x-4 top-[10%] z-50 mx-auto max-w-xl rounded-xl border border-edge bg-[#0d1117] shadow-2xl sm:inset-x-auto sm:left-1/2 sm:w-full sm:-translate-x-1/2"
          >
            {/* Header */}
            <div className="flex items-start justify-between border-b border-edge/60 p-4">
              <div>
                <div className="flex items-center gap-2">
                  <span className={`h-2.5 w-2.5 rounded-full ${STATUS_DOT[agent.status] ?? "bg-slate-600"}`} />
                  <h2 className="text-sm font-semibold text-slate-100">{agent.name}</h2>
                  {agent.is_head && (
                    <span className="rounded bg-hud-violet/20 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wider text-hud-violet">
                      Division Head
                    </span>
                  )}
                </div>
                <p className="mt-0.5 text-xs text-slate-500">
                  {agent.title} · {agent.division}
                </p>
              </div>
              <button
                onClick={onClose}
                className="rounded p-1 text-slate-500 hover:bg-slate-800 hover:text-slate-200"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="max-h-[70vh] overflow-y-auto p-4 space-y-4">
              {/* Status + Stats */}
              <div className="grid grid-cols-3 gap-2">
                {[
                  { label: "Status", value: agent.status.toUpperCase(), accent: STATUS_COLOR[agent.status] },
                  { label: "Tasks Done", value: agent.tasks_completed.toString(), accent: "text-hud-cyan" },
                  { label: "Success Rate", value: `${(agent.success_rate * 100).toFixed(0)}%`, accent: "text-hud-emerald" },
                ].map(({ label, value, accent }) => (
                  <div key={label} className="rounded-lg border border-edge/60 bg-panel-2/40 p-2.5 text-center">
                    <div className={`text-sm font-mono font-semibold ${accent}`}>{value}</div>
                    <div className="text-[9px] text-slate-500 mt-0.5">{label}</div>
                  </div>
                ))}
              </div>

              {/* Current Task */}
              <div>
                <div className="flex items-center gap-1.5 mb-1.5">
                  <Zap className="h-3.5 w-3.5 text-hud-amber" />
                  <span className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">Currently Working On</span>
                </div>
                <div className="rounded-lg border border-hud-amber/20 bg-hud-amber/5 px-3 py-2 text-xs text-slate-200">
                  {agent.current_task ?? agent.mission}
                </div>
                {agent.last_active && (
                  <p className="mt-1 text-[9px] text-slate-600">Last active {timeAgo(agent.last_active)}</p>
                )}
              </div>

              {/* Mission */}
              <div>
                <div className="flex items-center gap-1.5 mb-1.5">
                  <Target className="h-3.5 w-3.5 text-hud-violet" />
                  <span className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">Mission</span>
                </div>
                <p className="text-xs text-slate-300 leading-relaxed">{agent.mission}</p>
              </div>

              {/* Goals */}
              {agent.goals && agent.goals.length > 0 && (
                <div>
                  <div className="flex items-center gap-1.5 mb-1.5">
                    <CheckCircle className="h-3.5 w-3.5 text-hud-emerald" />
                    <span className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">Goals</span>
                  </div>
                  <ul className="space-y-1">
                    {agent.goals.map((g, i) => (
                      <li key={i} className="flex items-start gap-1.5 text-xs text-slate-300">
                        <span className="mt-0.5 text-hud-emerald">›</span>
                        {g}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {/* KPIs */}
              {agent.kpis && agent.kpis.length > 0 && (
                <div>
                  <div className="flex items-center gap-1.5 mb-1.5">
                    <TrendingUp className="h-3.5 w-3.5 text-hud-cyan" />
                    <span className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">KPIs</span>
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {agent.kpis.map((k, i) => (
                      <span key={i} className="rounded border border-hud-cyan/20 bg-hud-cyan/5 px-2 py-0.5 text-[10px] text-hud-cyan">
                        {k}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* Tools */}
              {agent.tools && agent.tools.length > 0 && (
                <div>
                  <div className="flex items-center gap-1.5 mb-1.5">
                    <Wrench className="h-3.5 w-3.5 text-slate-400" />
                    <span className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">Tools &amp; Capabilities</span>
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {agent.tools.map((t, i) => (
                      <span key={i} className="rounded border border-edge bg-panel-2/60 px-2 py-0.5 text-[10px] text-slate-400">
                        {t}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* Impact */}
              <div className="rounded-lg border border-hud-violet/20 bg-hud-violet/5 p-3">
                <div className="flex items-center justify-between">
                  <span className="text-[10px] text-slate-500">Empire Impact Score</span>
                  <span className="font-mono text-lg font-bold text-hud-violet">{agent.impact_score.toFixed(0)}</span>
                </div>
                <div className="mt-1.5 h-1.5 rounded-full bg-slate-800">
                  <div
                    className="h-1.5 rounded-full bg-hud-violet"
                    style={{ width: `${Math.min(agent.impact_score, 100)}%` }}
                  />
                </div>
              </div>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}
