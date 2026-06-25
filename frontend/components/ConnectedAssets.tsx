"use client";

import { Github, Globe2, Plug, Store } from "lucide-react";
import type { Connector } from "@/lib/types";
import { timeAgo } from "@/lib/format";

const ICON: Record<string, typeof Plug> = {
  github: Github,
  web_app: Globe2,
  marketplace: Store,
};

function summary(c: Connector): string {
  const m = c.metrics ?? {};
  if (c.kind === "github") {
    return `${Math.round(m.open_issues ?? 0)} open issues · pushed ${Math.round(
      m.days_since_push ?? 0,
    )}d ago`;
  }
  if (c.kind === "web_app") {
    return `${Math.round(m.traffic ?? 0).toLocaleString()} visits · ${m.conversion ?? 0}% conv`;
  }
  if (c.kind === "marketplace") {
    return `${Math.round(m.orders ?? 0)} orders · ${Math.round(
      m.impressions ?? 0,
    ).toLocaleString()} impressions`;
  }
  return c.status;
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
          const Icon = ICON[c.kind] ?? Plug;
          const live = c.status === "connected";
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
