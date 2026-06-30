"use client";

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { motion, AnimatePresence } from "framer-motion";
import { MessageSquare, Send, Target, TrendingUp, Wrench, X, Zap } from "lucide-react";
import type { AgentView } from "@/lib/types";
import { api } from "@/lib/api";
import { timeAgo } from "@/lib/format";

const STATUS_COLOR: Record<string, string> = {
  working: "text-hud-emerald",
  idle: "text-slate-400",
  blocked: "text-hud-rose",
  offline: "text-slate-600",
};

const STATUS_DOT: Record<string, string> = {
  working: "bg-hud-emerald",
  idle: "bg-slate-500",
  blocked: "bg-hud-rose",
  offline: "bg-slate-700",
};

interface Props {
  agent: AgentView | null;
  onClose: () => void;
}

type ChatTurn = { role: "you" | "agent"; text: string };

export function AgentDetailModal({ agent, onClose }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  // Portal target only exists in the browser — guard for the static export build.
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  const [chat, setChat] = useState<ChatTurn[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);

  // Reset the conversation whenever a different agent is opened.
  useEffect(() => {
    setChat([]);
    setInput("");
  }, [agent?.id]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [onClose]);

  const send = async () => {
    const q = input.trim();
    if (!agent || !q || sending) return;
    setInput("");
    setChat((c) => [...c, { role: "you", text: q }]);
    setSending(true);
    try {
      const res = await api.agentChat(agent.id, q);
      setChat((c) => [
        ...c,
        { role: "agent", text: res?.reply ?? "(No reply — set an LLM key like Groq, free, to chat.)" },
      ]);
    } finally {
      setSending(false);
    }
  };

  if (!mounted) return null;

  return createPortal(
    <AnimatePresence>
      {agent && (
        <>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
            className="fixed inset-0 z-[100] bg-black/60 backdrop-blur-sm"
          />
          <motion.div
            ref={ref}
            initial={{ opacity: 0, scale: 0.95, y: 20 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 20 }}
            transition={{ type: "spring", stiffness: 300, damping: 25 }}
            className="fixed inset-x-4 top-[8%] z-[101] mx-auto max-w-xl rounded-xl border border-edge bg-[#0d1117] shadow-2xl sm:inset-x-auto sm:left-1/2 sm:w-full sm:-translate-x-1/2"
          >
            <div className="flex items-start justify-between border-b border-edge/60 p-4">
              <div>
                <div className="flex items-center gap-2">
                  <span className={`h-2.5 w-2.5 rounded-full ${STATUS_DOT[agent.status] ?? "bg-slate-600"}`} />
                  <h2 className="text-sm font-semibold text-slate-100">{agent.name}</h2>
                  {agent.is_head && (
                    <span className="rounded bg-hud-violet/20 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wider text-hud-violet">
                      Division Head
                    </span>
                  )}
                </div>
                <p className="mt-0.5 text-xs text-slate-500">
                  {agent.title} · {agent.division}
                </p>
              </div>
              <button
                onClick={onClose}
                className="rounded p-1 text-slate-500 hover:bg-slate-800 hover:text-slate-200"
                aria-label="Close"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="max-h-[72vh] space-y-4 overflow-y-auto p-4">
              <div className="grid grid-cols-3 gap-2">
                {[
                  { label: "Status", value: agent.status.toUpperCase(), accent: STATUS_COLOR[agent.status] ?? "text-slate-300" },
                  { label: "Tasks Done", value: agent.tasks_completed.toString(), accent: "text-hud-cyan" },
                  { label: "Success Rate", value: `${(agent.success_rate * 100).toFixed(0)}%`, accent: "text-hud-emerald" },
                ].map(({ label, value, accent }) => (
                  <div key={label} className="rounded-lg border border-edge/60 bg-panel-2/40 p-2.5 text-center">
                    <div className={`font-mono text-sm font-semibold ${accent}`}>{value}</div>
                    <div className="mt-0.5 text-[9px] text-slate-500">{label}</div>
                  </div>
                ))}
              </div>

              {/* Talk to this agent */}
              <div className="rounded-lg border border-hud-cyan/20 bg-hud-cyan/5 p-3">
                <div className="mb-2 flex items-center gap-1.5">
                  <MessageSquare className="h-3.5 w-3.5 text-hud-cyan" />
                  <span className="text-[11px] font-semibold uppercase tracking-wide text-slate-300">
                    Talk to {agent.name.split(" ")[0]}
                  </span>
                </div>
                {chat.length > 0 && (
                  <div className="scroll-thin mb-2 max-h-40 space-y-2 overflow-y-auto pr-1">
                    {chat.map((t, i) => (
                      <div
                        key={i}
                        className={`text-xs leading-relaxed ${
                          t.role === "you" ? "text-slate-400" : "text-slate-200"
                        }`}
                      >
                        <span className={t.role === "you" ? "text-hud-amber" : "text-hud-cyan"}>
                          {t.role === "you" ? "You" : agent.name.split(" ")[0]}:
                        </span>{" "}
                        {t.text}
                      </div>
                    ))}
                    {sending && <div className="text-xs text-slate-500">…thinking</div>}
                  </div>
                )}
                <div className="flex items-center gap-2">
                  <input
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") void send();
                    }}
                    placeholder={`Ask ${agent.name.split(" ")[0]} anything…`}
                    className="flex-1 rounded-lg border border-edge bg-panel-2/60 px-2.5 py-1.5 text-xs text-slate-200 placeholder:text-slate-600 focus:border-hud-cyan/40 focus:outline-none"
                  />
                  <button
                    onClick={() => void send()}
                    disabled={sending || !input.trim()}
                    className="flex items-center gap-1 rounded-lg border border-hud-cyan/40 bg-hud-cyan/10 px-2.5 py-1.5 text-xs text-hud-cyan transition-colors hover:bg-hud-cyan/20 disabled:opacity-50"
                  >
                    <Send className="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>

              <div>
                <div className="mb-1.5 flex items-center gap-1.5">
                  <Zap className="h-3.5 w-3.5 text-hud-amber" />
                  <span className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">Currently Working On</span>
                </div>
                <div className="rounded-lg border border-hud-amber/20 bg-hud-amber/5 px-3 py-2 text-xs text-slate-200">
                  {agent.current_task ?? agent.mission}
                </div>
                {agent.last_active && (
                  <p className="mt-1 text-[9px] text-slate-600">Last active {timeAgo(agent.last_active)}</p>
                )}
              </div>

              <div>
                <div className="mb-1.5 flex items-center gap-1.5">
                  <Target className="h-3.5 w-3.5 text-hud-violet" />
                  <span className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">Mission</span>
                </div>
                <p className="text-xs leading-relaxed text-slate-300">{agent.mission}</p>
              </div>

              {agent.kpis && agent.kpis.length > 0 && (
                <div>
                  <div className="mb-1.5 flex items-center gap-1.5">
                    <TrendingUp className="h-3.5 w-3.5 text-hud-cyan" />
                    <span className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">KPIs</span>
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {agent.kpis.map((k, i) => (
                      <span key={i} className="rounded border border-hud-cyan/20 bg-hud-cyan/5 px-2 py-0.5 text-[10px] text-hud-cyan">
                        {k}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {agent.tools && agent.tools.length > 0 && (
                <div>
                  <div className="mb-1.5 flex items-center gap-1.5">
                    <Wrench className="h-3.5 w-3.5 text-slate-400" />
                    <span className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">Tools &amp; Capabilities</span>
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {agent.tools.map((t, i) => (
                      <span key={i} className="rounded border border-edge bg-panel-2/60 px-2 py-0.5 text-[10px] text-slate-400">
                        {t}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              <div className="rounded-lg border border-hud-violet/20 bg-hud-violet/5 p-3">
                <div className="flex items-center justify-between">
                  <span className="text-[10px] text-slate-500">Empire Impact Score</span>
                  <span className="font-mono text-lg font-bold text-hud-violet">{agent.impact_score.toFixed(0)}</span>
                </div>
                <div className="mt-1.5 h-1.5 rounded-full bg-slate-800">
                  <div className="h-1.5 rounded-full bg-hud-violet" style={{ width: `${Math.min(agent.impact_score, 100)}%` }} />
                </div>
              </div>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>,
    document.body,
  );
}
