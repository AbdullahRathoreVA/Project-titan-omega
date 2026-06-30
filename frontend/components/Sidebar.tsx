"use client";

import { useState } from "react";
import {
  Briefcase,
  ExternalLink,
  Facebook,
  Image as ImageIcon,
  Instagram,
  Linkedin,
  Mail,
  type LucideIcon,
} from "lucide-react";
import type { AgentView, ChannelTile } from "@/lib/types";
import { AgentDetailModal } from "./AgentDetailModal";

// lucide ships brand marks for some platforms but not all — sensible stand-ins
// for the rest (Pinterest → image, Upwork → briefcase, Gmail → mail).
const ICONS: Record<string, LucideIcon> = {
  instagram: Instagram,
  facebook: Facebook,
  linkedin: Linkedin,
  gmail: Mail,
  upwork: Briefcase,
  pinterest: ImageIcon,
};

const ACCENT: Record<string, string> = {
  rose: "text-hud-rose",
  blue: "text-hud-blue",
  cyan: "text-hud-cyan",
  emerald: "text-hud-emerald",
  amber: "text-hud-amber",
  violet: "text-hud-violet",
};

const STATUS_DOT: Record<string, string> = {
  working: "bg-hud-emerald shadow-glow-emerald",
  idle: "bg-slate-500",
  blocked: "bg-hud-rose",
  offline: "bg-slate-700",
};

export function Sidebar({
  channels,
  agents,
}: {
  channels: ChannelTile[];
  agents: AgentView[];
}) {
  const [selected, setSelected] = useState<AgentView | null>(null);
  const heads = [...agents]
    .filter((a) => a.is_head)
    .sort((a, b) => b.impact_score - a.impact_score)
    .slice(0, 8);

  return (
    <aside className="panel flex h-full flex-col gap-4 p-3">
      <AgentDetailModal agent={selected} onClose={() => setSelected(null)} />

      <div>
        <div className="hud-label mb-2 px-1">Channels</div>
        <div className="space-y-1">
          {channels.length === 0 && (
            <div className="px-1 py-2 text-[10px] text-slate-600">Connecting channels…</div>
          )}
          {channels.map((c) => {
            const Icon = ICONS[c.icon] ?? ExternalLink;
            const accent = ACCENT[c.accent] ?? "text-slate-300";
            const connected = c.status === "connected";
            return (
              <a
                key={c.id}
                href={c.href}
                target="_blank"
                rel="noreferrer"
                className="group flex items-center gap-2.5 rounded-lg border border-edge/60 bg-panel-2/40 px-2.5 py-2 transition-colors hover:border-hud-cyan/30 hover:bg-panel-2/80"
              >
                <Icon className={`h-4 w-4 shrink-0 ${accent}`} strokeWidth={1.7} />
                <span className="min-w-0 flex-1 truncate text-xs text-slate-200">{c.name}</span>
                {connected ? (
                  <span className="font-mono text-[11px] text-slate-300">
                    {c.value.toLocaleString()}
                    <span className="ml-1 text-[9px] text-slate-600">{c.label}</span>
                  </span>
                ) : (
                  <span className="rounded border border-edge px-1 text-[9px] uppercase tracking-wide text-slate-600">
                    connect
                  </span>
                )}
                <span
                  className={`h-1.5 w-1.5 shrink-0 rounded-full ${
                    connected ? "bg-hud-emerald" : "bg-slate-600"
                  }`}
                />
              </a>
            );
          })}
        </div>
      </div>

      <div className="min-h-0 flex-1">
        <div className="hud-label mb-2 px-1">Agents · Heads</div>
        <div className="scroll-thin h-full space-y-1 overflow-y-auto pr-0.5">
          {heads.map((a) => (
            <button
              key={a.id}
              onClick={() => setSelected(a)}
              className="flex w-full items-center gap-2.5 rounded-lg border border-edge/60 bg-panel-2/40 px-2.5 py-2 text-left transition-colors hover:border-hud-violet/30 hover:bg-panel-2/80"
            >
              <span
                className={`h-2 w-2 shrink-0 rounded-full ${STATUS_DOT[a.status] ?? "bg-slate-600"}`}
              />
              <div className="min-w-0 flex-1">
                <div className="truncate text-xs text-slate-200">{a.name}</div>
                <div className="truncate text-[10px] text-slate-500">
                  {a.current_task ?? a.mission}
                </div>
              </div>
            </button>
          ))}
        </div>
      </div>
    </aside>
  );
}
