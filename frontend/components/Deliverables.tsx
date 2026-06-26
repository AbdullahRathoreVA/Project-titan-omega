"use client";

import { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { ChevronDown, FileText, Sparkles } from "lucide-react";
import type { Deliverable } from "@/lib/types";
import { timeAgo } from "@/lib/format";

export function Deliverables({ items }: { items: Deliverable[] }) {
  const [openId, setOpenId] = useState<string | null>(null);

  return (
    <section className="panel flex h-full flex-col">
      <header className="panel-header">
        <div className="flex items-center gap-2">
          <FileText className="h-4 w-4 text-hud-amber" strokeWidth={1.6} />
          <h2 className="text-sm font-medium text-slate-200">Agent Deliverables</h2>
        </div>
        <span className="hud-label">{items.length} produced</span>
      </header>

      <div className="scroll-thin flex-1 space-y-2 overflow-y-auto p-3">
        {items.length === 0 && (
          <p className="px-1 py-6 text-center text-xs text-slate-500">
            No artifacts yet. Hit{" "}
            <span className="text-hud-emerald">Execute</span> on an opportunity and an
            agent will draft something real for you.
          </p>
        )}

        {items.map((d) => {
          const open = openId === d.id;
          return (
            <div key={d.id} className="rounded-lg border border-edge bg-panel-2/50">
              <button
                onClick={() => setOpenId(open ? null : d.id)}
                className="flex w-full items-start justify-between gap-2 px-3 py-2.5 text-left"
              >
                <div className="min-w-0">
                  <div className="flex items-center gap-1.5">
                    <span className="truncate text-xs text-slate-200">{d.title}</span>
                    {d.source === "ai" && (
                      <Sparkles className="h-3 w-3 shrink-0 text-hud-violet" />
                    )}
                  </div>
                  <div className="mt-0.5 text-[10px] text-slate-500">
                    {d.agent_name} · {timeAgo(d.created_at)} ·{" "}
                    <span
                      className={
                        d.source === "ai" ? "text-hud-violet" : "text-slate-500"
                      }
                    >
                      {d.source === "ai" ? "Claude" : "template"}
                    </span>
                  </div>
                </div>
                <ChevronDown
                  className={`mt-0.5 h-4 w-4 shrink-0 text-slate-500 transition-transform ${
                    open ? "rotate-180" : ""
                  }`}
                />
              </button>
              <AnimatePresence initial={false}>
                {open && (
                  <motion.pre
                    initial={{ opacity: 0, height: 0 }}
                    animate={{ opacity: 1, height: "auto" }}
                    exit={{ opacity: 0, height: 0 }}
                    className="scroll-thin overflow-x-auto whitespace-pre-wrap border-t border-edge/70 px-3 py-2.5 font-mono text-[11px] leading-relaxed text-slate-300"
                  >
                    {d.content}
                  </motion.pre>
                )}
              </AnimatePresence>
            </div>
          );
        })}
      </div>
    </section>
  );
}
