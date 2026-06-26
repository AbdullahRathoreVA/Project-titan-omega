"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import { CornerDownLeft, Mic, Terminal } from "lucide-react";
import { api } from "@/lib/api";
import type { CommandResponse } from "@/lib/types";

const SUGGESTIONS = [
  "Grow Career Mind AI traffic",
  "Find new revenue opportunities",
  "Optimize our Fiverr gigs",
  "Draft this week's growth plan",
];

export function CommandBar({ onDispatched }: { onDispatched?: () => void }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [reply, setReply] = useState<CommandResponse | null>(null);

  async function send(value: string) {
    const command = value.trim();
    if (!command || busy) return;
    setBusy(true);
    setReply(null);
    const res = await api.command(command);
    setReply(res);
    setText("");
    setBusy(false);
    onDispatched?.();
  }

  return (
    <div className="panel p-3 shadow-glow">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void send(text);
        }}
        className="flex items-center gap-2"
      >
        <Terminal className="h-4 w-4 shrink-0 text-hud-cyan" strokeWidth={1.6} />
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Command the empire…  e.g. “launch an affiliate program”"
          className="flex-1 bg-transparent font-mono text-sm text-slate-100 placeholder:text-slate-600 focus:outline-none"
          aria-label="Natural language command"
        />
        <button
          type="button"
          title="Voice control (coming soon)"
          className="rounded-md p-1.5 text-slate-500 transition-colors hover:text-hud-cyan"
        >
          <Mic className="h-4 w-4" strokeWidth={1.6} />
        </button>
        <button
          type="submit"
          disabled={busy}
          className="flex items-center gap-1.5 rounded-md border border-hud-cyan/40 bg-hud-cyan/10 px-3 py-1.5 text-xs font-medium text-hud-cyan transition-colors hover:bg-hud-cyan/20 disabled:opacity-50"
        >
          {busy ? "Dispatching…" : "Dispatch"}
          <CornerDownLeft className="h-3.5 w-3.5" />
        </button>
      </form>

      <div className="mt-2 flex flex-wrap gap-1.5">
        {SUGGESTIONS.map((s) => (
          <button
            key={s}
            onClick={() => void send(s)}
            className="rounded-full border border-edge px-2.5 py-1 text-[11px] text-slate-400 transition-colors hover:border-hud-cyan/40 hover:text-hud-cyan"
          >
            {s}
          </button>
        ))}
      </div>

      {reply && (
        <motion.div
          initial={{ opacity: 0, height: 0 }}
          animate={{ opacity: 1, height: "auto" }}
          className="mt-3 overflow-hidden rounded-lg border border-edge bg-panel-2/60 p-3"
        >
          <div className="flex items-center gap-2">
            <span className="hud-label">intent</span>
            <span className="rounded bg-hud-emerald/10 px-1.5 py-0.5 font-mono text-[10px] text-hud-emerald">
              {reply.intent}
            </span>
            {reply.routed_to && (
              <span className="font-mono text-[10px] text-slate-500">
                → {reply.routed_to}
              </span>
            )}
          </div>
          <p className="mt-1.5 text-xs leading-relaxed text-slate-300">{reply.response}</p>
        </motion.div>
      )}
    </div>
  );
}
