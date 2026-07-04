"use client";

import { useCallback, useEffect, useState } from "react";
import { Trophy } from "lucide-react";
import { api } from "@/lib/api";
import type { Progress } from "@/lib/types";

// Founder XP — computed ONLY from real events (revenue, wins, shipped work).
// No fake progress: at $0 and zero activity this honestly shows Level 1, 0 XP.
export function ProgressStrip() {
  const [p, setP] = useState<Progress | null>(null);

  const refresh = useCallback(async () => {
    setP(await api.progress());
  }, []);

  useEffect(() => {
    void refresh();
    const id = setInterval(() => void refresh(), 60000);
    return () => clearInterval(id);
  }, [refresh]);

  if (!p) return null;
  const span = Math.max(1, p.next_level_xp - p.level_floor);
  const pct = Math.min(100, Math.max(0, ((p.xp - p.level_floor) / span) * 100));
  const done = p.milestones.filter((m) => m.done).length;
  const next = p.milestones.find((m) => !m.done);

  return (
    <div className="panel mt-3 flex flex-wrap items-center gap-3 px-4 py-2">
      <div className="flex items-center gap-1.5">
        <Trophy className="h-3.5 w-3.5 text-hud-amber" />
        <span className="font-mono text-xs font-semibold text-hud-amber">LV {p.level}</span>
      </div>
      <div className="h-1.5 min-w-24 flex-1 overflow-hidden rounded-full bg-edge">
        <div
          className="h-full rounded-full bg-gradient-to-r from-hud-amber to-hud-emerald transition-all duration-700"
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="font-mono text-[10px] text-slate-500">
        {p.xp.toLocaleString()} / {p.next_level_xp.toLocaleString()} XP
      </span>
      <span className="text-[10px] text-slate-600">
        {done}/{p.milestones.length} milestones
        {next ? (
          <>
            {" · next: "}
            <span className="text-slate-400">{next.label}</span>
          </>
        ) : (
          " · all complete 🏆"
        )}
      </span>
    </div>
  );
}
