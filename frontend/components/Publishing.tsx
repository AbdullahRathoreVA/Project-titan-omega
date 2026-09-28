"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import { Send, Share2 } from "lucide-react";
import type { ScheduledPost } from "@/lib/types";
import { timeAgo } from "@/lib/format";
import { isCustomer } from "@/lib/session";

const CHANNELS = ["linkedin", "facebook", "pinterest", "instagram", "twitter"];

const STATUS_STYLE: Record<string, string> = {
  scheduled: "text-hud-cyan border-hud-cyan/40 bg-hud-cyan/10",
  queued: "text-hud-amber border-hud-amber/40 bg-hud-amber/10",
  published: "text-hud-emerald border-hud-emerald/40 bg-hud-emerald/10",
  failed: "text-hud-rose border-hud-rose/40 bg-hud-rose/10",
};

export function Publishing({
  posts,
  onSchedule,
  onPublish,
}: {
  posts: ScheduledPost[];
  onSchedule: (content: string, channels: string[]) => Promise<void> | void;
  onPublish: (id: string) => Promise<void> | void;
}) {
  const [content, setContent] = useState("");
  const [picked, setPicked] = useState<string[]>(["linkedin", "pinterest"]);
  const [busy, setBusy] = useState(false);

  function toggle(c: string) {
    setPicked((p) => (p.includes(c) ? p.filter((x) => x !== c) : [...p, c]));
  }

  async function submit() {
    if (!content.trim() || picked.length === 0 || busy) return;
    setBusy(true);
    try {
      await onSchedule(content.trim(), picked);
      setContent("");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel">
      <header className="panel-header">
        <div className="flex items-center gap-2">
          <Share2 className="h-4 w-4 text-hud-emerald" strokeWidth={1.6} />
          <h2 className="text-sm font-medium text-slate-200">Auto-Publishing</h2>
        </div>
        <span className="hud-label">{posts.length} in queue</span>
      </header>

      <div className="grid grid-cols-1 gap-4 p-3 lg:grid-cols-2">
        {/* compose */}
        <div className="space-y-2">
          <textarea
            value={content}
            onChange={(e) => setContent(e.target.value)}
            placeholder="Write a post, or let an agent draft it… then schedule to every channel."
            rows={4}
            className="w-full resize-none rounded-lg border border-edge bg-panel-2/60 p-2.5 text-xs text-slate-100 placeholder:text-slate-600 focus:border-hud-emerald/40 focus:outline-none"
          />
          <div className="flex flex-wrap gap-1.5">
            {CHANNELS.map((c) => (
              <button
                key={c}
                onClick={() => toggle(c)}
                className={`rounded-full border px-2.5 py-1 text-[11px] capitalize transition-colors ${
                  picked.includes(c)
                    ? "border-hud-emerald/50 bg-hud-emerald/10 text-hud-emerald"
                    : "border-edge text-slate-400 hover:text-slate-200"
                }`}
              >
                {c}
              </button>
            ))}
          </div>
          <button
            onClick={submit}
            disabled={busy}
            className="flex items-center gap-1.5 rounded-md border border-hud-emerald/40 bg-hud-emerald/10 px-3 py-1.5 text-xs font-medium text-hud-emerald transition-colors hover:bg-hud-emerald/20 disabled:opacity-50"
          >
            <Send className="h-3.5 w-3.5" />
            {busy ? "Scheduling…" : "Schedule post"}
          </button>
          {isCustomer() ? (
            <p className="text-[10px] leading-relaxed text-slate-600">
              Titan does not post to your accounts. Scheduled posts wait here as a
              ready queue — copy each one to your channels when it is due.
            </p>
          ) : (
            <p className="text-[10px] leading-relaxed text-slate-600">
              Set <span className="text-slate-400">TITAN_PUBLISH_WEBHOOK</span> (a free
              Zapier/Make/Buffer hook) and scheduled posts publish automatically — no
              passwords, no ban risk. Until then they wait here as a ready queue.
            </p>
          )}
        </div>

        {/* queue */}
        <div className="scroll-thin max-h-64 space-y-2 overflow-y-auto">
          {posts.length === 0 && (
            <p className="px-1 py-6 text-center text-xs text-slate-500">
              Nothing scheduled yet.
            </p>
          )}
          {posts.map((p) => (
            <motion.div
              key={p.id}
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              className="rounded-lg border border-edge bg-panel-2/50 p-2.5"
            >
              <div className="flex items-start justify-between gap-2">
                <p className="line-clamp-2 text-xs text-slate-300">{p.content}</p>
                <span
                  className={`shrink-0 rounded border px-1.5 py-0.5 text-[9px] uppercase ${
                    STATUS_STYLE[p.status] ?? "text-slate-400 border-edge"
                  }`}
                >
                  {p.status}
                </span>
              </div>
              <div className="mt-1.5 flex items-center justify-between">
                <span className="text-[10px] text-slate-500">
                  {p.channels.join(" · ")} · {timeAgo(p.scheduled_at)}
                </span>
                {(p.status === "scheduled" || p.status === "queued") && (
                  <button
                    onClick={() => onPublish(p.id)}
                    className="rounded border border-hud-emerald/40 px-1.5 py-0.5 text-[10px] text-hud-emerald hover:bg-hud-emerald/10"
                  >
                    Publish now
                  </button>
                )}
              </div>
            </motion.div>
          ))}
        </div>
      </div>
    </section>
  );
}
