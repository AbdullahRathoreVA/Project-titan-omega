"use client";

import { motion } from "framer-motion";
import { Network } from "lucide-react";
import type { DivisionView } from "@/lib/types";

function healthColor(h: number): string {
  if (h >= 80) return "bg-hud-emerald";
  if (h >= 60) return "bg-hud-cyan";
  if (h >= 40) return "bg-hud-amber";
  return "bg-hud-rose";
}

export function DivisionGrid({ divisions }: { divisions: DivisionView[] }) {
  return (
    <section className="panel">
      <header className="panel-header">
        <div className="flex items-center gap-2">
          <Network className="h-4 w-4 text-hud-cyan" strokeWidth={1.6} />
          <h2 className="text-sm font-medium text-slate-200">Autonomous Divisions</h2>
        </div>
        <span className="hud-label">{divisions.length} active</span>
      </header>
      <div className="grid grid-cols-2 gap-2 p-3 sm:grid-cols-3 lg:grid-cols-4">
        {divisions.map((d, i) => (
          <motion.div
            key={d.division}
            initial={{ opacity: 0, scale: 0.96 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ delay: i * 0.03 }}
            className="group rounded-lg border border-edge bg-panel-2/60 p-3 transition-colors hover:border-hud-cyan/50"
          >
            <div className="flex items-center justify-between">
              <span className="font-mono text-[11px] uppercase tracking-wider text-hud-cyan/80">
                {d.division}
              </span>
              <span className="text-[10px] text-slate-500">
                {d.active_agents}/{d.agent_count}
              </span>
            </div>
            <div className="mt-1 truncate text-xs text-slate-300">{d.head}</div>
            <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-edge">
              <div
                className={`h-full rounded-full ${healthColor(d.health)}`}
                style={{ width: `${d.health}%` }}
              />
            </div>
            <div className="mt-1 text-right font-mono text-[10px] text-slate-400">
              {d.health.toFixed(0)}%
            </div>
          </motion.div>
        ))}
      </div>
    </section>
  );
}
