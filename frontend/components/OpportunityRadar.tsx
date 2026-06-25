"use client";

import { motion } from "framer-motion";
import { Radar, TrendingUp } from "lucide-react";
import type { Opportunity } from "@/lib/types";
import { money } from "@/lib/format";

// Place each opportunity on the radar: angle by index, radius by inverse
// priority (higher priority sits closer to the center / the operator).
function blip(i: number, total: number, priority: number) {
  const angle = (i / Math.max(total, 1)) * Math.PI * 2 - Math.PI / 2;
  const radius = 12 + (100 - priority) * 0.36; // % from center
  return {
    left: `${50 + Math.cos(angle) * radius}%`,
    top: `${50 + Math.sin(angle) * radius}%`,
  };
}

export function OpportunityRadar({ opportunities }: { opportunities: Opportunity[] }) {
  const top = opportunities.slice(0, 8);
  return (
    <section className="panel flex h-full flex-col">
      <header className="panel-header">
        <div className="flex items-center gap-2">
          <Radar className="h-4 w-4 text-hud-emerald" strokeWidth={1.6} />
          <h2 className="text-sm font-medium text-slate-200">Global Opportunity Radar</h2>
        </div>
        <span className="hud-label">{opportunities.length} tracked</span>
      </header>

      <div className="relative mx-auto my-4 aspect-square w-48">
        {/* radar rings */}
        {[1, 0.66, 0.33].map((r) => (
          <div
            key={r}
            className="absolute rounded-full border border-hud-emerald/20"
            style={{
              inset: `${(1 - r) * 50}%`,
            }}
          />
        ))}
        {/* sweep */}
        <div className="absolute inset-0 animate-sweep">
          <div className="absolute left-1/2 top-0 h-1/2 w-px origin-bottom bg-gradient-to-t from-hud-emerald/60 to-transparent" />
        </div>
        <div className="absolute left-1/2 top-1/2 h-1.5 w-1.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-hud-emerald shadow-glow-emerald" />
        {/* blips */}
        {top.map((o, i) => (
          <motion.div
            key={o.id}
            initial={{ scale: 0 }}
            animate={{ scale: 1 }}
            transition={{ delay: i * 0.06 }}
            title={o.title}
            className="absolute h-2 w-2 -translate-x-1/2 -translate-y-1/2 rounded-full bg-hud-cyan shadow-glow"
            style={blip(i, top.length, o.priority_score)}
          />
        ))}
      </div>

      <div className="scroll-thin flex-1 space-y-2 overflow-y-auto px-3 pb-3">
        {top.map((o) => (
          <div
            key={o.id}
            className="rounded-lg border border-edge bg-panel-2/50 p-2.5"
          >
            <div className="flex items-start justify-between gap-2">
              <span className="text-xs leading-snug text-slate-200">{o.title}</span>
              <span className="shrink-0 rounded bg-hud-emerald/10 px-1.5 py-0.5 font-mono text-[10px] text-hud-emerald">
                {o.priority_score.toFixed(0)}
              </span>
            </div>
            <div className="mt-1.5 flex items-center gap-3 text-[10px] text-slate-400">
              <span className="flex items-center gap-1 text-hud-emerald">
                <TrendingUp className="h-3 w-3" /> {money(o.expected_revenue)}
              </span>
              <span>risk {o.risk.toFixed(0)}</span>
              <span>{o.time_estimate_days.toFixed(0)}d</span>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
