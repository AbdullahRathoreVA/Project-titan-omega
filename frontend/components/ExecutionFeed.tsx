"use client";

import { AnimatePresence, motion } from "framer-motion";
import { Activity, ArrowLeftRight } from "lucide-react";
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
          {events.map((e) =>
            e.kind === "handoff" ? (
              // Inter-division hand-off — rendered as a distinct "collaboration"
              // row so the network visibly cooperates, not just logs events.
              <motion.div
                key={e.id}
                initial={{ opacity: 0, x: -8 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0 }}
                className="my-0.5 flex items-start gap-2 rounded border border-hud-violet/25 bg-gradient-to-r from-hud-violet/10 to-hud-cyan/5 px-2 py-1.5"
              >
                <span className="mt-0.5 text-[10px] text-slate-600">{timeAgo(e.timestamp)}</span>
                <ArrowLeftRight className="mt-0.5 h-3 w-3 shrink-0 animate-pulse text-hud-violet" strokeWidth={2} />
                <span className="leading-snug">
                  <span className="mr-1 rounded bg-hud-violet/20 px-1 text-[9px] font-semibold uppercase tracking-wide text-hud-violet">
                    handoff
                  </span>
                  <span className="bg-gradient-to-r from-hud-violet to-hud-cyan bg-clip-text text-transparent">
                    {e.message}
                  </span>
                </span>
              </motion.div>
            ) : (
              <motion.div
                key={e.id}
                initial={{ opacity: 0, x: -8 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0 }}
                className="flex items-start gap-2 rounded px-2 py-1 hover:bg-panel-2/60"
              >
                <span className="mt-0.5 text-[10px] text-slate-600">{timeAgo(e.timestamp)}</span>
                <span className={`mt-0.5 ${SEVERITY_COLOR[e.severity] ?? "text-slate-400"}`}>▍</span>
                <span className="leading-snug text-slate-300">
                  <span className="text-slate-500">[{e.actor}]</span> {e.message}
                </span>
              </motion.div>
            ),
          )}
        </AnimatePresence>
      </div>
    </section>
  );
}
