"use client";

// Mission Control — the unified live operations view (Vision X slice 4+6):
// execution queues, priority/opportunity queue, risk alerts, agent health,
// and the AI memory timeline (council decisions), all from live data.

import { motion } from "framer-motion";
import {
  AlertTriangle,
  Brain,
  CheckCircle2,
  ListTodo,
  Radar,
  ShieldAlert,
  Users,
} from "lucide-react";
import type {
  AgentView,
  DecisionEntry,
  EmpireStatus,
  ExecutionItem,
  FeedEvent,
  Opportunity,
} from "@/lib/types";
import { timeAgo } from "@/lib/format";

const EXEC_STYLE: Record<string, string> = {
  running: "text-hud-cyan border-hud-cyan/40",
  pending: "text-hud-amber border-hud-amber/40",
  completed: "text-hud-emerald border-hud-emerald/40",
  failed: "text-hud-rose border-hud-rose/40",
  reverted: "text-slate-500 border-edge",
};

function Meter({ label, value, max, tone }: { label: string; value: number; max: number; tone: string }) {
  const pct = max > 0 ? Math.round((value / max) * 100) : 0;
  return (
    <div>
      <div className="flex justify-between font-mono text-[10px] text-slate-500">
        <span>{label}</span>
        <span>
          {value}/{max}
        </span>
      </div>
      <div className="mt-0.5 h-1 overflow-hidden rounded-full bg-panel-2">
        <motion.div
          className={`h-full rounded-full ${tone}`}
          animate={{ width: `${pct}%` }}
          transition={{ duration: 0.6, ease: "easeOut" }}
        />
      </div>
    </div>
  );
}

export function MissionControl({
  status,
  agents,
  opportunities,
  executions,
  decisions,
  feed,
}: {
  status: EmpireStatus | null;
  agents: AgentView[];
  opportunities: Opportunity[];
  executions: ExecutionItem[];
  decisions: DecisionEntry[];
  feed: FeedEvent[];
}) {
  const working = agents.filter((a) => a.status === "working").length;
  const blocked = agents.filter((a) => a.status === "blocked").length;
  const risks = feed.filter((e) => e.severity === "warn" || e.severity === "critical").slice(0, 6);
  const active = executions.filter((e) => e.status === "running" || e.status === "pending").slice(0, 8);
  const doneCount = executions.filter((e) => e.status === "completed").length;
  const failCount = executions.filter((e) => e.status === "failed").length;
  const topOpps = opportunities.slice(0, 6);

  return (
    <div className="grid gap-4 xl:grid-cols-3">
      {/* Column 1 — execution queue */}
      <section className="panel">
        <header className="panel-header">
          <div className="flex items-center gap-2">
            <ListTodo className="h-4 w-4 text-hud-cyan" strokeWidth={1.6} />
            <h2 className="text-sm font-medium text-slate-200">Task Queue</h2>
          </div>
          <span className="hud-label">
            {doneCount} done · {failCount} failed
          </span>
        </header>
        <div className="scroll-thin max-h-[420px] space-y-1.5 overflow-y-auto p-2">
          {active.length === 0 && (
            <p className="px-2 py-6 text-center text-xs text-slate-600">
              Queue clear — agents are on autonomous workflows.
            </p>
          )}
          {active.map((e) => (
            <div key={e.id} className={`rounded-lg border bg-panel-2/40 px-2.5 py-2 ${EXEC_STYLE[e.status] ?? "border-edge"}`}>
              <div className="flex items-center justify-between gap-2">
                <span className="truncate text-xs text-slate-200">{e.title}</span>
                <span className="shrink-0 font-mono text-[9px] uppercase">{e.status}</span>
              </div>
              <div className="mt-0.5 flex justify-between text-[10px] text-slate-500">
                <span>{String(e.division)}</span>
                <span>{timeAgo(e.updated_at)}</span>
              </div>
            </div>
          ))}
          {/* completed tail */}
          {executions
            .filter((e) => e.status === "completed")
            .slice(0, 3)
            .map((e) => (
              <div key={e.id} className="flex items-center gap-2 px-2.5 py-1 text-[11px] text-slate-500">
                <CheckCircle2 className="h-3 w-3 text-hud-emerald" /> <span className="truncate">{e.title}</span>
              </div>
            ))}
        </div>
      </section>

      {/* Column 2 — priority queue + risk alerts */}
      <section className="panel">
        <header className="panel-header">
          <div className="flex items-center gap-2">
            <Radar className="h-4 w-4 text-hud-violet" strokeWidth={1.6} />
            <h2 className="text-sm font-medium text-slate-200">Priority Queue</h2>
          </div>
          <span className="hud-label">{status?.open_opportunities ?? 0} open</span>
        </header>
        <div className="scroll-thin max-h-[250px] space-y-1.5 overflow-y-auto p-2">
          {topOpps.map((o, i) => (
            <div key={o.id} className="flex items-center gap-2 rounded-lg border border-edge/60 bg-panel-2/40 px-2.5 py-2">
              <span className="font-mono text-[11px] text-hud-violet">#{i + 1}</span>
              <span className="min-w-0 flex-1 truncate text-xs text-slate-200">{o.title}</span>
              <span className="font-mono text-[11px] text-hud-cyan">{Math.round(o.priority_score)}</span>
            </div>
          ))}
        </div>
        <header className="panel-header border-t border-edge/60">
          <div className="flex items-center gap-2">
            <ShieldAlert className="h-4 w-4 text-hud-rose" strokeWidth={1.6} />
            <h2 className="text-sm font-medium text-slate-200">Risk Alerts</h2>
          </div>
        </header>
        <div className="scroll-thin max-h-[140px] space-y-1 overflow-y-auto p-2">
          {risks.length === 0 && (
            <p className="px-2 py-3 text-center text-[11px] text-slate-600">No active risks flagged.</p>
          )}
          {risks.map((r) => (
            <div key={r.id} className="flex items-start gap-2 rounded px-2 py-1 text-[11px]">
              <AlertTriangle
                className={`mt-0.5 h-3 w-3 shrink-0 ${r.severity === "critical" ? "text-hud-rose" : "text-hud-amber"}`}
              />
              <span className="leading-snug text-slate-400">{r.message}</span>
            </div>
          ))}
        </div>
      </section>

      {/* Column 3 — agent health + memory timeline */}
      <section className="panel">
        <header className="panel-header">
          <div className="flex items-center gap-2">
            <Users className="h-4 w-4 text-hud-emerald" strokeWidth={1.6} />
            <h2 className="text-sm font-medium text-slate-200">Agent Health</h2>
          </div>
          <span className="hud-label">health {status ? status.health.toFixed(0) : "—"}</span>
        </header>
        <div className="space-y-2 p-3">
          <Meter label="Working" value={working} max={agents.length || 1} tone="bg-hud-emerald" />
          <Meter label="Blocked" value={blocked} max={agents.length || 1} tone="bg-hud-rose" />
          <Meter
            label="Actions in flight"
            value={status?.actions_in_flight ?? 0}
            max={Math.max(5, status?.actions_in_flight ?? 0)}
            tone="bg-hud-cyan"
          />
        </div>
        <header className="panel-header border-t border-edge/60">
          <div className="flex items-center gap-2">
            <Brain className="h-4 w-4 text-hud-violet" strokeWidth={1.6} />
            <h2 className="text-sm font-medium text-slate-200">Memory Timeline</h2>
          </div>
          <span className="hud-label">{decisions.length} decisions</span>
        </header>
        <div className="scroll-thin max-h-[210px] space-y-1.5 overflow-y-auto p-2">
          {decisions.length === 0 && (
            <p className="px-2 py-4 text-center text-[11px] text-slate-600">
              No council decisions recorded yet — run the War Room.
            </p>
          )}
          {decisions.slice(0, 8).map((d, i) => (
            <div key={i} className="rounded-lg border border-hud-violet/20 bg-hud-violet/5 px-2.5 py-2">
              <div className="flex items-center justify-between gap-2">
                <span className="truncate text-[11px] text-slate-300">{d.goal}</span>
                <span className="shrink-0 font-mono text-[10px] text-hud-violet">{d.confidence}%</span>
              </div>
              <div className="mt-0.5 text-[10px] text-slate-600">{timeAgo(d.time)}</div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
