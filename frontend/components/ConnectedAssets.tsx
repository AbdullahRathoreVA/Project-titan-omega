"use client";

import { BookOpen, Github, Globe2, Plug, Store } from "lucide-react";
import type { Connector } from "@/lib/types";
import { timeAgo } from "@/lib/format";

const ICON: Record<string, typeof Plug> = {
  github: Github,
  web_app: Globe2,
  marketplace: Store,
};

// Override icon for Kindle
function getIcon(c: Connector) {
  if (c.name?.toLowerCase().includes("kindle") || c.name?.toLowerCase().includes("amazon")) {
    return BookOpen;
  }
  return ICON[c.kind] ?? Plug;
}

function fmt(n: number): string {
  return Math.round(n).toLocaleString();
}

function summary(c: Connector): string {
  const m = c.metrics ?? {};
  if (c.kind === "github") {
    return `${Math.round(m.open_issues ?? 0)} open issues · pushed ${Math.round(m.days_since_push ?? 0)}d ago`;
  }
  if (c.kind === "web_app") {
    const total = m.total_users ?? 0;
    const activeUsers = m.active_users ?? 0;
    const signups = m.signups ?? 0;
    const visits = m.traffic ?? 0;
    if (total > 0 || activeUsers > 0) {
      return `${fmt(total)} users · ${fmt(activeUsers)} active · ${fmt(signups)} signups`;
    }
    if (visits > 0) {
      return `${fmt(visits)} visits · ${m.conversion ?? 0}% conv`;
    }
    return "Waiting for first users — agents promoting now";
  }
  if (c.kind === "marketplace") {
    // Kindle
    if (c.name?.toLowerCase().includes("kindle") || c.name?.toLowerCase().includes("amazon")) {
      const units = m.units_sold ?? 0;
      const royalties = m.royalties ?? 0;
      const reviews = m.reviews ?? 0;
      if (units > 0) return `${fmt(units)} units sold · $${royalties.toFixed(0)} royalties`;
      return reviews > 0 ? `${reviews} reviews · awaiting sales` : "Awaiting first sale — agents promoting";
    }
    // Fiverr
    return `${Math.round(m.orders ?? 0)} orders · ${fmt(m.impressions ?? 0)} impressions`;
  }
  return c.status;
}

function detail(c: Connector): string | null {
  const m = c.metrics ?? {};
  if (c.kind === "web_app") {
    const online = (m.platform_online ?? 0) >= 1;
    const conv = m.conversion ?? 0;
    const ret = m.retention ?? 0;
    return `${online ? "🟢 live" : "— offline"} · ${conv}% conv · ${ret}% retention`;
  }
  if (c.name?.toLowerCase().includes("kindle")) {
    const rank = m.ranking ?? 0;
    return rank > 0 ? `Amazon rank #${fmt(rank)} in category` : "KDP listing active — share your book link";
  }
  return null;
}

export function ConnectedAssets({ connectors }: { connectors: Connector[] }) {
  return (
    <section className="panel">
      <header className="panel-header">
        <div className="flex items-center gap-2">
          <Plug className="h-4 w-4 text-hud-cyan" strokeWidth={1.6} />
          <h2 className="text-sm font-medium text-slate-200">Connected Business Assets</h2>
        </div>
        <span className="hud-label">{connectors.length} monitored</span>
      </header>
      <div className="grid grid-cols-1 gap-2 p-3 sm:grid-cols-2 lg:grid-cols-4">
        {connectors.map((c) => {
          const Icon = getIcon(c);
          const live = c.status === "connected";
          const extra = detail(c);
          return (
            <div
              key={c.id}
              className="flex items-start gap-2.5 rounded-lg border border-edge bg-panel-2/60 p-2.5"
            >
              <Icon className="mt-0.5 h-4 w-4 shrink-0 text-slate-300" strokeWidth={1.6} />
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-1.5">
                  <span className="truncate text-xs text-slate-200">{c.name}</span>
                  <span
                    className={`h-1.5 w-1.5 shrink-0 rounded-full ${
                      live ? "bg-hud-emerald" : "bg-hud-amber"
                    }`}
                  />
                </div>
                <div className="mt-0.5 truncate text-[10px] text-slate-500">{summary(c)}</div>
                {extra && (
                  <div className="truncate text-[9px] text-slate-600">{extra}</div>
                )}
                <div className="text-[9px] text-slate-600">
                  {live ? `synced ${timeAgo(c.last_sync)}` : c.status}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
