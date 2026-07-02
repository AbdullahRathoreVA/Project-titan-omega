"use client";

import { useCallback, useEffect, useState } from "react";
import { CheckCircle2, MessageCircle, ShieldCheck, Smartphone } from "lucide-react";
import { api } from "@/lib/api";
import type { TelegramLogEntry, TelegramStatus } from "@/lib/types";

// Telegram Command Center page: live command/response log + one-time setup.
export function TelegramCenter() {
  const [status, setStatus] = useState<TelegramStatus | null>(null);
  const [log, setLog] = useState<TelegramLogEntry[]>([]);

  const refresh = useCallback(async () => {
    const [s, l] = await Promise.all([api.telegramStatus(), api.telegramLog(60)]);
    setStatus(s);
    setLog(l);
  }, []);

  useEffect(() => {
    void refresh();
    const id = setInterval(() => void refresh(), 6000);
    return () => clearInterval(id);
  }, [refresh]);

  const configured = status?.configured ?? false;

  return (
    <div className="space-y-4">
      <section className="panel">
        <header className="panel-header">
          <div className="flex items-center gap-2">
            <MessageCircle className="h-4 w-4 text-hud-cyan" strokeWidth={1.6} />
            <h2 className="text-sm font-medium text-slate-200">Telegram Command Center</h2>
          </div>
          <div className="flex items-center gap-3">
            {status?.locked && (
              <span className="flex items-center gap-1 text-[10px] text-hud-emerald">
                <ShieldCheck className="h-3 w-3" /> locked to your chat
              </span>
            )}
            <span
              className={`flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[10px] ${
                configured
                  ? "border-hud-emerald/40 text-hud-emerald"
                  : "border-hud-amber/40 text-hud-amber"
              }`}
            >
              <span className={`h-1.5 w-1.5 rounded-full ${configured ? "bg-hud-emerald" : "bg-hud-amber"}`} />
              {configured ? "bot connected" : "not configured"}
            </span>
          </div>
        </header>

        {!configured && (
          <div className="space-y-2 p-4 text-xs text-slate-300">
            <div className="flex items-center gap-2 text-slate-200">
              <Smartphone className="h-4 w-4 text-hud-cyan" />
              <span className="font-semibold">Command Titan from your phone — free, 5 minutes:</span>
            </div>
            <ol className="list-decimal space-y-1.5 pl-5 text-slate-400">
              <li>In Telegram, open <span className="text-hud-cyan">@BotFather</span> → send <span className="font-mono text-slate-300">/newbot</span> → pick a name → copy the token.</li>
              <li>HF Space → Settings → Variables and secrets → add secret <span className="font-mono text-slate-300">TELEGRAM_BOT_TOKEN</span> = your token.</li>
              <li>Factory reboot the Space, then message your bot <span className="font-mono text-slate-300">/start</span>.</li>
              <li>Your chat id appears in the log below — add it as secret <span className="font-mono text-slate-300">TELEGRAM_CHAT_ID</span> so ONLY you can command Titan, and reboot once more.</li>
            </ol>
            <p className="text-slate-500">
              Then from anywhere: /status · /revenue · /agents · /opportunities · /report · /news · /search · /ask · /nextpost · /approve
            </p>
          </div>
        )}

        <div className="p-3">
          <div className="hud-label mb-2">Command log · {status?.handled ?? 0} handled</div>
          {log.length === 0 ? (
            <div className="py-6 text-center text-[11px] text-slate-600">
              No commands yet{configured ? " — message your bot /start" : ""}.
            </div>
          ) : (
            <div className="scroll-thin max-h-[480px] space-y-2 overflow-y-auto pr-1">
              {log.map((e, i) => (
                <div key={i} className="rounded-lg border border-edge/60 bg-panel-2/40 p-2.5">
                  <div className="flex items-center justify-between text-[10px] text-slate-500">
                    <span>
                      <span className="text-hud-amber">{e.from}</span> · chat {e.chat_id}
                    </span>
                    <span className="font-mono">{new Date(e.time).toLocaleTimeString()}</span>
                  </div>
                  <div className="mt-1 font-mono text-xs text-slate-200">{e.command}</div>
                  <div className="mt-1 flex items-start gap-1.5 text-[11px] text-slate-400">
                    <CheckCircle2 className="mt-0.5 h-3 w-3 shrink-0 text-hud-emerald" />
                    <span className="whitespace-pre-line">{e.reply}</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </section>
    </div>
  );
}
