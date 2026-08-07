"use client";

/**
 * VoiceAgents — the Voice Agent OS command screen.
 *
 * The rule this screen is built to: **every visual state maps to a real
 * backend event, every metric comes from actual data.** Nothing here is
 * decorative. Concretely:
 *
 * - Each orbiting node is one live session from `/api/voice/live`. No sessions
 *   means no nodes — not a demo ring of fake agents.
 * - Node colour is the session's real state from the server's state machine.
 *   The machine refuses illegal transitions, so a colour on this screen is a
 *   state the agent genuinely occupied.
 * - Latency renders only where it was measured. Cost renders as "not billed"
 *   because no provider is charging — never `$0.00`, which would claim a
 *   measurement nobody took.
 * - Approve buttons hit the real approval gate. A sensitive tool cannot be
 *   marked executed without one, and the server returns 403 if you try.
 *
 * The orbital view is plain canvas, like VoiceSphere: no 3D library, no new
 * dependency, and it runs on integrated graphics.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import {
  AlertTriangle, Bell, BellOff, CheckCircle2, Headphones, History, Loader2,
  PhoneForwarded, RefreshCw, ShieldQuestion, Radio,
} from "lucide-react";
import VoiceSphere from "./VoiceSphere";

type SessionRow = {
  id: string;
  channel: string;
  agent: string;
  language: string;
  caller: string;
  state: string;
  duration_s: number;
  turns: number;
  tools: number;
  pending_approvals: number;
  escalated: boolean;
  escalation: { reason: string; to: string } | null;
  avg_thinking_ms: number | null;
  cost_usd: number | null;
};

type Live = {
  summary: string;
  active: SessionRow[];
  active_count: number;
  total_sessions: number;
  by_state: Record<string, number>;
  by_channel: Record<string, number>;
  pending_approvals: number;
  escalated: number;
  median_thinking_ms: number | null;
  measured_latency_sessions: number;
  cost_usd: number | null;
  cost_note: string;
  channels_supported: string[];
};

type Detail = SessionRow & {
  turns_detail: { role: string; text: string; at: number; language: string; confidence: number | null }[];
  tools_detail: {
    id: string; name: string; args_summary: string; requires_approval: boolean;
    status: string; ok: boolean | null; error: string; approved_by: string | null;
  }[];
  state_history: { state: string; at: number; reason?: string }[];
};

type Capabilities = Record<string, { ready: boolean; cost: string; note: string }> & {
  channels: string[];
};

/** State → colour. One place, so the orbit and the list can never disagree. */
const STATE_TONE: Record<string, { text: string; dot: string; rgb: string }> = {
  idle:        { text: "text-slate-400",    dot: "bg-slate-500",     rgb: "148,163,184" },
  listening:   { text: "text-hud-emerald",  dot: "bg-hud-emerald",   rgb: "52,211,153" },
  thinking:    { text: "text-hud-violet",   dot: "bg-hud-violet",    rgb: "167,139,250" },
  speaking:    { text: "text-hud-cyan",     dot: "bg-hud-cyan",      rgb: "34,211,238" },
  interrupted: { text: "text-hud-amber",    dot: "bg-hud-amber",     rgb: "251,191,36" },
  escalated:   { text: "text-hud-rose",     dot: "bg-hud-rose",      rgb: "251,113,133" },
  ended:       { text: "text-slate-600",    dot: "bg-slate-700",     rgb: "71,85,105" },
};

function tone(state: string) {
  return STATE_TONE[state] ?? STATE_TONE.idle;
}

function token(): string {
  if (typeof window === "undefined") return "";
  return localStorage.getItem("titan_token") || sessionStorage.getItem("titan_token") || "";
}

async function call<T>(path: string, init?: RequestInit): Promise<T | null> {
  try {
    const r = await fetch(`/api/voice${path}`, {
      ...init,
      cache: "no-store",
      headers: {
        Authorization: `Bearer ${token()}`,
        ...(init?.body ? { "Content-Type": "application/json" } : {}),
      },
    });
    if (!r.ok) return null;
    return (await r.json()) as T;
  } catch {
    return null;
  }
}

/** Orbiting session nodes. One node per live session — never a decorative ring. */
function Orbit({ sessions }: { sessions: SessionRow[] }) {
  const ref = useRef<HTMLCanvasElement | null>(null);
  const rowsRef = useRef<SessionRow[]>(sessions);
  rowsRef.current = sessions;

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d", { alpha: true });
    if (!ctx) return;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    let W = 0, H = 0, raf = 0, t = 0, last = performance.now();
    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const r = canvas.getBoundingClientRect();
      W = Math.max(1, Math.round(r.width));
      H = Math.max(1, Math.round(r.height));
      canvas.width = Math.round(W * dpr);
      canvas.height = Math.round(H * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    resize();
    window.addEventListener("resize", resize);

    const frame = (now: number) => {
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;
      t += reduced ? dt * 0.2 : dt;
      ctx.clearRect(0, 0, W, H);

      const rows = rowsRef.current;
      const cx = W / 2, cy = H / 2;
      const R = Math.min(W, H) * 0.36;

      // Orbit path — drawn only when something is on it.
      if (rows.length) {
        ctx.strokeStyle = "rgba(148,163,184,0.10)";
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.ellipse(cx, cy, R, R * 0.42, 0, 0, Math.PI * 2);
        ctx.stroke();
      }

      rows.forEach((s, i) => {
        const a = (i / Math.max(1, rows.length)) * Math.PI * 2 + t * 0.35;
        const x = cx + Math.cos(a) * R;
        const y = cy + Math.sin(a) * R * 0.42;
        const depth = (Math.sin(a) + 1) / 2;      // front nodes larger
        const c = tone(s.state).rgb;

        // Active states pulse; idle and ended sit still. The motion IS the
        // state — an idle node that throbbed would be decoration.
        const live = s.state === "speaking" || s.state === "listening" || s.state === "thinking";
        const pulse = live ? 1 + Math.sin(t * 4 + i) * 0.18 : 1;
        const rad = (5 + depth * 5) * pulse;

        const g = ctx.createRadialGradient(x, y, 0, x, y, rad * 3.4);
        g.addColorStop(0, `rgba(${c},${0.5 + depth * 0.45})`);
        g.addColorStop(1, `rgba(${c},0)`);
        ctx.fillStyle = g;
        ctx.beginPath();
        ctx.arc(x, y, rad * 3.4, 0, Math.PI * 2);
        ctx.fill();

        ctx.fillStyle = `rgba(${c},${0.65 + depth * 0.35})`;
        ctx.beginPath();
        ctx.arc(x, y, rad, 0, Math.PI * 2);
        ctx.fill();

        // Tether to the core, brighter when the session is doing something.
        ctx.strokeStyle = `rgba(${c},${live ? 0.24 : 0.09})`;
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(cx, cy);
        ctx.lineTo(x, y);
        ctx.stroke();

        ctx.fillStyle = `rgba(226,232,240,${0.35 + depth * 0.4})`;
        ctx.font = "9px ui-monospace, SFMono-Regular, Menlo, monospace";
        ctx.textAlign = "center";
        ctx.fillText(s.channel, x, y - rad - 7);
      });

      raf = requestAnimationFrame(frame);
    };
    raf = requestAnimationFrame(frame);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", resize);
    };
  }, []);

  return <canvas ref={ref} className="pointer-events-none absolute inset-0 h-full w-full" />;
}

export default function VoiceAgents() {
  const [live, setLive] = useState<Live | null>(null);
  const [caps, setCaps] = useState<Capabilities | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [busy, setBusy] = useState(false);
  const [acting, setActing] = useState<string | null>(null);
  const [history, setHistory] = useState<SessionRow[] | null>(null);
  const [showHistory, setShowHistory] = useState(false);
  const [alerts, setAlerts] = useState<NotificationPermission | "unsupported">("default");
  // Previous counts, so an alert fires on a genuine INCREASE rather than on
  // every poll while a number simply stays high.
  const seen = useRef<{ escalated: number; pending: number } | null>(null);

  useEffect(() => {
    if (typeof window === "undefined") return;
    setAlerts("Notification" in window ? Notification.permission : "unsupported");
  }, []);

  const load = useCallback(async () => {
    setBusy(true);
    try {
      const [l, c] = await Promise.all([
        call<Live>("/live"),
        call<Capabilities>("/capabilities"),
      ]);
      setLive(l);
      setCaps(c);

      if (l) {
        const prev = seen.current;
        if (prev && typeof window !== "undefined" &&
            "Notification" in window && Notification.permission === "granted") {
          if (l.escalated > prev.escalated) {
            new Notification("Titan — a call needs a person", {
              body: "A voice session escalated to a human.",
              tag: "titan-escalation",
            });
          } else if (l.pending_approvals > prev.pending) {
            new Notification("Titan — waiting on your approval", {
              body: `${l.pending_approvals} action${l.pending_approvals === 1 ? "" : "s"} blocked until you approve.`,
              tag: "titan-approval",
            });
          }
        }
        seen.current = { escalated: l.escalated, pending: l.pending_approvals };
      }
    } finally {
      setBusy(false);
    }
  }, []);

  const loadHistory = useCallback(async () => {
    const h = await call<{ sessions: SessionRow[] }>("/sessions?limit=60");
    setHistory(h?.sessions ?? []);
  }, []);

  useEffect(() => {
    void load();
    const t = setInterval(load, 4000);
    return () => clearInterval(t);
  }, [load]);

  useEffect(() => {
    if (!selected) {
      setDetail(null);
      return;
    }
    let stop = false;
    const pull = async () => {
      const d = await call<Detail>(`/sessions/${selected}`);
      if (!stop) setDetail(d);
    };
    void pull();
    const t = setInterval(pull, 3000);
    return () => {
      stop = true;
      clearInterval(t);
    };
  }, [selected]);

  const approve = async (sid: string, callId: string) => {
    setActing(callId);
    await call(`/sessions/${sid}/tool/${callId}/approve`, {
      method: "POST",
      body: JSON.stringify({ approver: "abdullah" }),
    });
    setActing(null);
    void load();
    const d = await call<Detail>(`/sessions/${sid}`);
    setDetail(d);
  };

  const sessions = live?.active ?? [];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 text-sm font-semibold tracking-widest text-white">
            <Radio className="h-4 w-4 text-hud-cyan" /> VOICE AGENTS
          </div>
          {/* The plain-language line. It is the sentence a non-engineer reads. */}
          <div className="mt-1 text-[11px] text-slate-400">
            {live ? live.summary : "Loading…"}
          </div>
        </div>
        <div className="flex gap-2">
          {/* Never auto-prompt for notifications — browsers penalise it and it
              is a dark pattern. Asked for only on a deliberate click. */}
          {alerts !== "unsupported" && (
            <button
              onClick={async () => {
                if (alerts === "granted") return;
                const p = await Notification.requestPermission();
                setAlerts(p);
              }}
              title={
                alerts === "granted"
                  ? "Alerts fire while this screen is open. A true background push would need a server that can reach a push service — this one cannot."
                  : "Get notified when a call escalates or an action needs approval"
              }
              className={`flex items-center gap-1 rounded-lg border px-3 py-1.5 text-[11px] transition ${
                alerts === "granted"
                  ? "border-hud-emerald/40 bg-hud-emerald/10 text-hud-emerald"
                  : alerts === "denied"
                    ? "border-white/10 text-slate-600"
                    : "border-white/10 text-slate-300 hover:border-hud-amber/50 hover:text-hud-amber"
              }`}
            >
              {alerts === "granted" ? <Bell className="h-3 w-3" /> : <BellOff className="h-3 w-3" />}
              {alerts === "granted" ? "Alerts on" : alerts === "denied" ? "Alerts blocked" : "Alert me"}
            </button>
          )}
          <button
            onClick={() => {
              setShowHistory((v) => !v);
              if (!history) void loadHistory();
            }}
            className={`flex items-center gap-1 rounded-lg border px-3 py-1.5 text-[11px] transition ${
              showHistory
                ? "border-hud-cyan/50 bg-hud-cyan/10 text-hud-cyan"
                : "border-white/10 text-slate-300 hover:border-hud-cyan/50 hover:text-hud-cyan"
            }`}
          >
            <History className="h-3 w-3" /> History
          </button>
          <button
            onClick={() => {
              void load();
              if (showHistory) void loadHistory();
            }}
            className="flex items-center gap-1 rounded-lg border border-white/10 px-3 py-1.5 text-[11px] text-slate-300 transition hover:border-hud-cyan/50 hover:text-hud-cyan"
          >
            <RefreshCw className={`h-3 w-3 ${busy ? "animate-spin" : ""}`} /> Refresh
          </button>
        </div>
      </div>

      {alerts === "granted" && (
        <div className="text-[10px] text-slate-600">
          Alerts fire while this screen is open. Titan cannot push to you in the
          background — the container cannot reach Telegram (verified: SSL
          handshake timeout) and no push service is configured.
        </div>
      )}

      {/* headline numbers — each one counted from stored sessions */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        {[
          ["Live now", String(live?.active_count ?? 0),
            (live?.active_count ?? 0) > 0 ? "text-hud-cyan" : "text-slate-500"],
          ["Sessions", String(live?.total_sessions ?? 0), "text-white"],
          ["Awaiting you", String(live?.pending_approvals ?? 0),
            (live?.pending_approvals ?? 0) > 0 ? "text-hud-amber" : "text-slate-500"],
          ["Escalated", String(live?.escalated ?? 0),
            (live?.escalated ?? 0) > 0 ? "text-hud-rose" : "text-slate-500"],
          // Latency shows only where a clock was actually read.
          ["Median think",
            live?.median_thinking_ms != null ? `${Math.round(live.median_thinking_ms)}ms` : "—",
            "text-hud-violet"],
        ].map(([label, value, t]) => (
          <div key={label as string} className="rounded-xl border border-white/10 bg-black/30 px-4 py-3">
            <div className={`font-mono text-2xl font-semibold leading-none ${t}`}>{value}</div>
            <div className="mt-1 text-[10px] uppercase tracking-widest text-slate-500">{label}</div>
          </div>
        ))}
      </div>
      {live && live.median_thinking_ms == null && (
        <div className="text-[10px] text-slate-600">
          No latency yet — no session has passed through “thinking”. Shown as “—”
          rather than 0 ms, which would read as instantaneous.
        </div>
      )}

      {/* the core + orbiting sessions */}
      <div className="relative overflow-hidden rounded-xl border border-edge">
        <VoiceSphere height={300} />
        <Orbit sessions={sessions} />
        {sessions.length === 0 && (
          <div className="pointer-events-none absolute inset-x-0 bottom-4 text-center text-[11px] text-slate-500">
            No live sessions. The orbit is empty because nothing is running —
            not because it is still loading.
          </div>
        )}
      </div>

      <div className="grid gap-3 lg:grid-cols-2">
        {/* live sessions */}
        <div className="rounded-xl border border-white/10 bg-black/30 p-4">
          <div className="text-[11px] font-semibold uppercase tracking-widest text-slate-300">
            Live sessions
          </div>
          {sessions.length === 0 ? (
            <p className="mt-3 text-[11px] text-slate-500">
              Nothing running. Start one from any channel and it appears here
              within four seconds.
            </p>
          ) : (
            <div className="mt-3 space-y-1.5">
              {sessions.map((s) => (
                <button
                  key={s.id}
                  onClick={() => setSelected(s.id === selected ? null : s.id)}
                  className={`flex w-full items-center gap-3 rounded-lg border px-3 py-2 text-left transition ${
                    selected === s.id
                      ? "border-hud-cyan/50 bg-hud-cyan/5"
                      : "border-transparent hover:border-white/10"
                  }`}
                >
                  <span className={`h-2 w-2 shrink-0 rounded-full ${tone(s.state).dot}`} />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[12px] text-slate-200">
                      {s.caller || s.agent}
                      <span className="ml-2 text-slate-500">{s.channel}</span>
                    </span>
                    <span className="block text-[10px] text-slate-500">
                      {s.turns} turn{s.turns === 1 ? "" : "s"} · {s.language} ·{" "}
                      {Math.round(s.duration_s)}s
                      {s.avg_thinking_ms != null && ` · ${Math.round(s.avg_thinking_ms)}ms think`}
                    </span>
                  </span>
                  <span className={`shrink-0 font-mono text-[10px] uppercase ${tone(s.state).text}`}>
                    {s.state}
                  </span>
                  {s.pending_approvals > 0 && (
                    <ShieldQuestion className="h-3.5 w-3.5 shrink-0 text-hud-amber" />
                  )}
                  {s.escalated && (
                    <PhoneForwarded className="h-3.5 w-3.5 shrink-0 text-hud-rose" />
                  )}
                </button>
              ))}
            </div>
          )}

          {/* finished sessions — replay is first-class, not a live-only view */}
          {showHistory && (
            <div className="mt-4 border-t border-white/5 pt-3">
              <div className="text-[10px] uppercase tracking-widest text-slate-600">
                Finished sessions
              </div>
              {history === null ? (
                <p className="mt-2 text-[11px] text-slate-600">Loading…</p>
              ) : history.filter((s) => s.state === "ended").length === 0 ? (
                <p className="mt-2 text-[11px] text-slate-600">
                  Nothing has finished yet.
                </p>
              ) : (
                <div className="mt-2 space-y-1">
                  {history
                    .filter((s) => s.state === "ended")
                    .map((s) => (
                      <button
                        key={s.id}
                        onClick={() => setSelected(s.id === selected ? null : s.id)}
                        className={`flex w-full items-center gap-3 rounded-lg border px-3 py-1.5 text-left transition ${
                          selected === s.id
                            ? "border-hud-cyan/50 bg-hud-cyan/5"
                            : "border-transparent hover:border-white/10"
                        }`}
                      >
                        <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-slate-700" />
                        <span className="min-w-0 flex-1 truncate text-[11px] text-slate-400">
                          {s.caller || s.agent}
                          <span className="ml-2 text-slate-600">{s.channel}</span>
                        </span>
                        <span className="shrink-0 font-mono text-[10px] text-slate-600">
                          {s.turns}t · {Math.round(s.duration_s)}s
                        </span>
                        {s.escalated && (
                          <PhoneForwarded className="h-3 w-3 shrink-0 text-hud-rose" />
                        )}
                      </button>
                    ))}
                </div>
              )}
            </div>
          )}

          {/* channels — reported from configuration, never from intent */}
          {caps && (
            <div className="mt-4 border-t border-white/5 pt-3">
              <div className="text-[10px] uppercase tracking-widest text-slate-600">
                Channels and providers
              </div>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {(["browser_speech", "livekit", "premium_tts", "telephony"] as const).map((k) => {
                  const c = caps[k];
                  if (!c) return null;
                  return (
                    <span
                      key={k}
                      title={c.note}
                      className={`cursor-help rounded-full border px-2 py-0.5 font-mono text-[9px] uppercase tracking-wider ${
                        c.ready
                          ? "border-hud-emerald/40 bg-hud-emerald/10 text-hud-emerald"
                          : "border-white/10 bg-white/5 text-slate-500"
                      }`}
                    >
                      {k.replace("_", " ")} {c.ready ? "ready" : "not configured"}
                    </span>
                  );
                })}
              </div>
            </div>
          )}
        </div>

        {/* transcript + tool timeline */}
        <div className="rounded-xl border border-white/10 bg-black/30 p-4">
          <div className="text-[11px] font-semibold uppercase tracking-widest text-slate-300">
            {detail ? `Session ${detail.id}` : "Transcript"}
          </div>
          {!detail ? (
            <p className="mt-3 text-[11px] text-slate-500">
              Select a session to replay its transcript, tool calls and state
              timeline.
            </p>
          ) : (
            <>
              {detail.escalation && (
                <div className="mt-3 flex items-start gap-2 rounded-lg border border-hud-rose/30 bg-hud-rose/5 px-3 py-2 text-[10px] text-hud-rose">
                  <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />
                  <span>
                    Escalated to {detail.escalation.to}: {detail.escalation.reason}
                  </span>
                </div>
              )}

              <div className="mt-3 max-h-52 space-y-2 overflow-y-auto pr-1">
                {detail.turns_detail.length === 0 ? (
                  <p className="text-[11px] text-slate-600">Nothing said yet.</p>
                ) : (
                  detail.turns_detail.map((t, i) => (
                    <div key={i} className="text-[11.5px]">
                      <span
                        className={`mr-2 font-mono text-[9px] uppercase ${
                          t.role === "user" ? "text-hud-emerald" : "text-hud-cyan"
                        }`}
                      >
                        {t.role}
                      </span>
                      <span className="text-slate-300">{t.text}</span>
                      {t.confidence != null && (
                        <span className="ml-2 font-mono text-[9px] text-slate-600">
                          {(t.confidence * 100).toFixed(0)}%
                        </span>
                      )}
                    </div>
                  ))
                )}
              </div>

              {detail.tools_detail.length > 0 && (
                <div className="mt-4 border-t border-white/5 pt-3">
                  <div className="text-[10px] uppercase tracking-widest text-slate-600">
                    Tool calls
                  </div>
                  <div className="mt-2 space-y-1.5">
                    {detail.tools_detail.map((c) => (
                      <div key={c.id} className="flex items-center gap-2 text-[11px]">
                        {c.status === "done" ? (
                          <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-hud-emerald" />
                        ) : c.status === "pending" ? (
                          <ShieldQuestion className="h-3.5 w-3.5 shrink-0 text-hud-amber" />
                        ) : c.status === "failed" ? (
                          <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-hud-rose" />
                        ) : (
                          <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-slate-500" />
                        )}
                        <span className="min-w-0 flex-1 truncate text-slate-300">
                          {c.name}
                          {c.args_summary && (
                            <span className="ml-1.5 text-slate-600">{c.args_summary}</span>
                          )}
                        </span>
                        {c.status === "pending" ? (
                          // Hits the real gate. Without this the server returns
                          // 403 on execution — the block is not cosmetic.
                          <button
                            onClick={() => void approve(detail.id, c.id)}
                            disabled={acting === c.id}
                            className="shrink-0 rounded border border-hud-amber/40 bg-hud-amber/10 px-2 py-0.5 font-mono text-[9px] uppercase text-hud-amber transition hover:bg-hud-amber/20 disabled:opacity-50"
                          >
                            {acting === c.id ? "…" : "Approve"}
                          </button>
                        ) : (
                          <span className="shrink-0 font-mono text-[9px] text-slate-600">
                            {c.approved_by ? `by ${c.approved_by}` : c.status}
                          </span>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              <div className="mt-4 border-t border-white/5 pt-3">
                <div className="text-[10px] uppercase tracking-widest text-slate-600">
                  State timeline
                </div>
                <div className="mt-2 flex flex-wrap items-center gap-1">
                  {detail.state_history.map((h, i) => (
                    <span key={i} className="flex items-center gap-1">
                      {i > 0 && <span className="text-slate-700">›</span>}
                      <span className={`font-mono text-[10px] ${tone(h.state).text}`}>
                        {h.state}
                      </span>
                    </span>
                  ))}
                </div>
              </div>
            </>
          )}
        </div>
      </div>

      {/* the one number nobody is measuring */}
      {live && (
        <div className="flex items-start gap-2 rounded-lg border border-white/10 bg-black/20 px-3 py-2 text-[10px] leading-relaxed text-slate-500">
          <Headphones className="mt-0.5 h-3 w-3 shrink-0 text-slate-600" />
          <span>{live.cost_note}</span>
        </div>
      )}
    </div>
  );
}
