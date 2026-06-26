"use client";

import { motion } from "framer-motion";
import type { LucideIcon } from "lucide-react";

export function MetricCard({
  label,
  value,
  sub,
  icon: Icon,
  accent = "cyan",
}: {
  label: string;
  value: string;
  sub?: string;
  icon: LucideIcon;
  accent?: "cyan" | "emerald" | "amber" | "violet" | "blue";
}) {
  const ring = {
    cyan: "text-hud-cyan",
    emerald: "text-hud-emerald",
    amber: "text-hud-amber",
    violet: "text-hud-violet",
    blue: "text-hud-blue",
  }[accent];

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className="panel relative overflow-hidden px-4 py-3"
    >
      <div className="flex items-start justify-between">
        <span className="hud-label">{label}</span>
        <Icon className={`h-4 w-4 ${ring}`} strokeWidth={1.6} />
      </div>
      <div className="mt-2 stat-value">{value}</div>
      {sub && <div className="mt-0.5 text-xs text-slate-400">{sub}</div>}
      <div
        className={`pointer-events-none absolute -right-6 -top-6 h-16 w-16 rounded-full ${ring} opacity-10 blur-xl`}
      />
    </motion.div>
  );
}
