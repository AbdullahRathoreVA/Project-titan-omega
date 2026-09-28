"use client";

import { BrainCircuit, Hexagon, Wifi, WifiOff } from "lucide-react";
import type { EmpireStatus, IntelligenceStatus } from "@/lib/types";
import { customerProfile, isCustomer } from "@/lib/session";

export function StatusBar({
  status,
  online,
  intel,
}: {
  status: EmpireStatus | null;
  online: boolean;
  intel: IntelligenceStatus | null;
}) {
  const claude = intel?.claude_connected ?? false;
  // A subscriber sees their plan, not the founder's model configuration.
  const customer = isCustomer();
  const plan = customerProfile()?.plan_name ?? "Free";
  return (
    <header className="flex flex-col gap-3 border-b border-edge/70 pb-4 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex items-center gap-3">
        <div className="relative">
          <Hexagon className="h-9 w-9 animate-flicker text-hud-cyan" strokeWidth={1.4} />
          <span className="absolute inset-0 flex items-center justify-center text-[10px] font-bold text-hud-cyan">
            ΤΩ
          </span>
        </div>
        <div>
          <h1 className="font-mono text-lg font-semibold tracking-wide text-white">
            TITAN<span className="text-hud-cyan"> OMEGA</span>
          </h1>
          <p className="text-[11px] tracking-wide text-slate-500">
            {customer ? "Your autonomous business · Command Center" : "Autonomous Founder Empire · Command Center"}
          </p>
        </div>
      </div>

      <div className="flex items-center gap-4">
        <div className="flex items-center gap-2">
          <span className="hud-label">Empire Health</span>
          <div className="h-2 w-28 overflow-hidden rounded-full bg-edge">
            <div
              className="h-full rounded-full bg-gradient-to-r from-hud-cyan to-hud-emerald transition-all"
              style={{ width: `${status?.health ?? 0}%` }}
            />
          </div>
          <span className="font-mono text-sm text-hud-emerald">
            {status ? status.health.toFixed(0) : "––"}
          </span>
        </div>

        <div
          className={`flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] ${
            claude
              ? "border-hud-violet/40 text-hud-violet"
              : "border-edge text-slate-400"
          }`}
          title={
            customer
              ? `Your plan: ${plan}`
              : claude
                ? `Agents thinking with ${intel?.model}`
                : "Free mode — set ANTHROPIC_API_KEY to enable Claude reasoning"
          }
        >
          <BrainCircuit className="h-3.5 w-3.5" />
          {customer ? `${plan} plan` : claude ? "Claude online" : "Free mode"}
        </div>

        <div
          className={`flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] ${
            online
              ? "border-hud-emerald/40 text-hud-emerald"
              : "border-hud-amber/40 text-hud-amber"
          }`}
        >
          {online ? <Wifi className="h-3.5 w-3.5" /> : <WifiOff className="h-3.5 w-3.5" />}
          {online ? "Core online" : "Core offline (demo)"}
        </div>
      </div>
    </header>
  );
}
