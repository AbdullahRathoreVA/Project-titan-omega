"use client";

// Neural Command Universe — wrapper. Maps Titan's REAL live data into the 3D
// scene (metric nodes, division galaxies, activity comets) and renders the
// glassmorphic hologram window when something is selected. Nothing here is
// decorative: every glow and comet is driven by actual state.

import { Component, useMemo, useState, type ReactNode } from "react";
import dynamic from "next/dynamic";
import { motion, AnimatePresence } from "framer-motion";
import { ArrowRight, X } from "lucide-react";
import type { AgentView, DivisionView, EmpireStatus, ScheduledPost } from "@/lib/types";
import type { UniGalaxy, UniMetric, UniSelection } from "./Universe3D";
import { compact, money } from "@/lib/format";
import { tap } from "@/lib/sound";

const Scene = dynamic(() => import("./Universe3D"), {
  ssr: false,
  loading: () => (
    <div className="flex h-full items-center justify-center font-mono text-xs text-hud-cyan animate-pulseGlow">
      Expanding the universe…
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
        3D unavailable on this device — every other tab still works.
      </div>
    ) : (
      this.props.children
    );
  }
}

// Division → energy color, per the command-universe spec: marketing rose,
// engineering blue, sales/revenue green, finance gold, research purple.
const DIVISION_COLOR: Record<string, string> = {
  marketing: "#fb7185",
  customer: "#fb7185",
  technology: "#3b82f6",
  product: "#3b82f6",
  revenue: "#34d399",
  partnerships: "#34d399",
  finance: "#fbbf24",
  operations: "#fbbf24",
  intelligence: "#a78bfa",
  innovation: "#a78bfa",
  executive: "#22d3ee",
  growth: "#22d3ee",
};

const METRIC_DESC: Record<string, { desc: string; goto: string; gotoLabel: string }> = {
  revenue: { desc: "Total real revenue in the ledger — every dollar verified.", goto: "finance", gotoLabel: "Open Finance" },
  traffic: { desc: "Monthly visitors (connects via Make.com analytics push).", goto: "dashboard", gotoLabel: "Open Dashboard" },
  pipeline: { desc: "Open value across ranked opportunities.", goto: "dashboard", gotoLabel: "Open Dashboard" },
  agents: { desc: "Digital employees working right now across 12 divisions.", goto: "city", gotoLabel: "Enter AI City" },
  opportunities: { desc: "Ranked opportunities discovered by the intelligence engines.", goto: "dashboard", gotoLabel: "Open Radar" },
  actions: { desc: "Actions currently in flight through the execution engine.", goto: "dashboard", gotoLabel: "Open Dashboard" },
  posts: { desc: "Posts scheduled through the publishing pipeline.", goto: "dashboard", gotoLabel: "Open Publishing" },
  health: { desc: "Empire health — agent success blended with impact.", goto: "city", gotoLabel: "Enter AI City" },
};

const STATUS_DOT: Record<string, string> = {
  working: "bg-hud-emerald",
  idle: "bg-slate-500",
  blocked: "bg-hud-rose",
  offline: "bg-slate-700",
};

export function Universe({
  status,
  divisions,
  agents,
  posts,
  intensity,
  pulse,
  onNavigate,
}: {
  status: EmpireStatus | null;
  divisions: DivisionView[];
  agents: AgentView[];
  posts: ScheduledPost[];
  intensity: number;
  pulse: number;
  onNavigate: (view: string) => void;
}) {
  const [selected, setSelected] = useState<UniSelection>(null);

  const metrics: UniMetric[] = useMemo(
    () => [
      { key: "revenue", label: "Revenue", value: money(status?.mrr ?? 0), color: "#34d399" },
      { key: "traffic", label: "Traffic", value: compact(status?.traffic ?? 0), color: "#22d3ee" },
      { key: "pipeline", label: "Pipeline", value: money(status?.pipeline_value ?? 0), color: "#a78bfa" },
      { key: "agents", label: "Agents", value: `${status?.active_agents ?? 0}/${status?.total_agents ?? 0}`, color: "#3b82f6" },
      { key: "opportunities", label: "Opportunities", value: `${status?.open_opportunities ?? 0}`, color: "#fbbf24" },
      { key: "actions", label: "In flight", value: `${status?.actions_in_flight ?? 0}`, color: "#fb7185" },
      { key: "posts", label: "Posts", value: `${posts.length}`, color: "#22d3ee" },
      { key: "health", label: "Health", value: `${(status?.health ?? 0).toFixed(0)}`, color: "#34d399" },
    ],
    [status, posts.length],
  );

  const galaxies: UniGalaxy[] = useMemo(
    () =>
      divisions.map((d) => ({
        key: d.division,
        label: d.division,
        color: DIVISION_COLOR[d.division] ?? "#22d3ee",
        active: d.active_agents,
        total: d.agent_count,
      })),
    [divisions],
  );

  const selMetric = selected?.type === "metric" ? metrics.find((m) => m.key === selected.key) : null;
  const selDivision = selected?.type === "galaxy" ? divisions.find((d) => d.division === selected.key) : null;
  const districtAgents = selDivision
    ? agents
        .filter((a) => a.division === selDivision.division)
        .sort((a, b) => b.impact_score - a.impact_score)
        .slice(0, 5)
    : [];

  return (
    // 78vh with a 540px floor took 658px of an 844px phone — 78% of the
    // screen for the visualization, pushing every actionable control below
    // the fold. On desktop that cinematic scale is the point; on a phone it
    // is the reason the dashboard cannot be operated.
    //
    // 52vh/320px floor on mobile leaves room for the stat cards and the tab
    // strip in the same screen. Desktop is unchanged from `sm` up.
    <div className="relative h-[52vh] min-h-[320px] overflow-hidden rounded-xl border border-edge/60 sm:h-[78vh] sm:min-h-[540px]">
      <div className="absolute inset-0">
        <Boundary>
          <Scene
            metrics={metrics}
            galaxies={galaxies}
            intensity={intensity}
            pulse={pulse}
            selected={selected}
            onSelect={(sel) => {
              tap();
              setSelected(sel);
            }}
          />
        </Boundary>
      </div>

      {/* HUD */}
      <div className="pointer-events-none absolute left-4 top-3 z-10">
        <div className="font-mono text-[11px] tracking-[0.3em] text-hud-cyan/80">TITAN Ω · NEURAL COMMAND</div>
        <div className="mt-0.5 text-[10px] text-slate-600">every glow is real activity · click anything — the camera flies</div>
      </div>
      <div className="pointer-events-none absolute bottom-3 left-4 z-10 font-mono text-[10px] text-slate-600">
        core intensity {(intensity * 100).toFixed(0)}% · {galaxies.length} division galaxies · {metrics.length} live nodes
      </div>

      {/* Hologram window */}
      <AnimatePresence>
        {(selMetric || selDivision) && (
          <motion.div
            key={selected?.type === "metric" ? selected.key : selDivision?.division}
            initial={{ opacity: 0, scale: 0.8, y: 24, filter: "blur(8px)" }}
            animate={{ opacity: 1, scale: 1, y: 0, filter: "blur(0px)" }}
            exit={{ opacity: 0, scale: 0.85, y: 12, filter: "blur(8px)" }}
            transition={{ type: "spring", stiffness: 260, damping: 24 }}
            className="absolute right-4 top-12 z-20 w-[270px] rounded-2xl border border-hud-cyan/25 bg-panel/40 shadow-glow backdrop-blur-xl"
          >
            <div className="flex items-center justify-between border-b border-hud-cyan/15 px-4 py-2.5">
              <span className="font-mono text-[10px] uppercase tracking-[0.25em] text-hud-cyan">
                {selMetric ? selMetric.label : `${selDivision?.division} galaxy`}
              </span>
              <button
                onClick={() => setSelected(null)}
                className="rounded p-0.5 text-slate-500 hover:text-hud-cyan"
                aria-label="Close hologram"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </div>

            {selMetric && (
              <div className="space-y-3 p-4">
                <div className="font-mono text-3xl font-semibold" style={{ color: selMetric.color }}>
                  {selMetric.value}
                </div>
                <p className="text-[11px] leading-relaxed text-slate-400">
                  {METRIC_DESC[selMetric.key]?.desc}
                </p>
                <button
                  onClick={() => onNavigate(METRIC_DESC[selMetric.key]?.goto ?? "dashboard")}
                  className="flex w-full items-center justify-center gap-1.5 rounded-lg border border-hud-cyan/40 bg-hud-cyan/10 px-3 py-1.5 text-xs text-hud-cyan hover:bg-hud-cyan/20"
                >
                  {METRIC_DESC[selMetric.key]?.gotoLabel ?? "Open"} <ArrowRight className="h-3 w-3" />
                </button>
              </div>
            )}

            {selDivision && (
              <div className="space-y-2.5 p-4">
                <div className="text-[10px] text-slate-500">
                  Head: <span className="text-slate-300">{selDivision.head}</span> · health{" "}
                  <span className="text-hud-emerald">{selDivision.health.toFixed(0)}</span> ·{" "}
                  {selDivision.active_agents}/{selDivision.agent_count} active
                </div>
                <div className="space-y-1">
                  {districtAgents.map((a) => (
                    <div key={a.id} className="flex items-center gap-2 rounded-lg border border-edge/50 bg-panel-2/40 px-2 py-1.5">
                      <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${STATUS_DOT[a.status] ?? "bg-slate-600"}`} />
                      <span className="min-w-0 flex-1 truncate text-[11px] text-slate-300">{a.name}</span>
                    </div>
                  ))}
                </div>
                <button
                  onClick={() => onNavigate("city")}
                  className="flex w-full items-center justify-center gap-1.5 rounded-lg border border-hud-cyan/40 bg-hud-cyan/10 px-3 py-1.5 text-xs text-hud-cyan hover:bg-hud-cyan/20"
                >
                  Enter the AI City <ArrowRight className="h-3 w-3" />
                </button>
              </div>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
