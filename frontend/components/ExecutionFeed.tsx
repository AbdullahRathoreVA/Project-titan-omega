"use client";

import { AnimatePresence, motion } from "framer-motion";
import { Activity } from "lucide-react";
import type { FeedEvent } from "@/lib/types";
import { SEVERITY_COLOR, timeAgo } from "@/lib/format";

export function ExecutionFeed({ events }: { events: FeedEvent[] }) {
  return (
    <section className="panel flex h-full flex-col">
      <header className="panel-header">
        <div className="flex items-center gap-2">
          <Activity className="h-4 w-4 text-hud-cyan" strokeWidth={1.6} />
          <h2 className="text-sm font-medium text-slate-200">Live Execution Feed</h2>
        </div>
        <span className="flex items-center gap-1.5 hud-label">
          <span className="h-1.5 w-1.5 animate-pulseGlow rounded-full bg-hud-emerald" />
          streaming
        </span>
      </header>
      <div className="scroll-thin flex-1 space-y-1 overflow-y-auto p-2 font-mono text-xs">
        <AnimatePresence initial={false}>
          {events.map((e) => (
            <motion.div
              key={e.id}
              initial={{ opacity: 0, x: -8 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0 }}
              className="flex items-start gap-2 rounded px-2 py-1 hover:bg-panel-2/60"
            >
              <span className="mt-0.5 text-[10px] text-slate-600">{timeAgo(e.timestamp)}</span>
              <span className={`mt-0.5 ${SEVERITY_COLOR[e.severity] ?? "text-slate-400"}`}>
                ▍
              </span>
              <span className="leading-snug text-slate-300">
                <span className="text-slate-500">[{e.actor}]</span> {e.message}
              </span>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
    </section>
  );
}
