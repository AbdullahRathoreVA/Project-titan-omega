"use client";

import { useState } from "react";
import { CheckCircle2, ImageOff, RefreshCw, Send } from "lucide-react";
import type { NextPost as NextPostType } from "@/lib/types";
import { api } from "@/lib/api";

// The HUD "Next Post" card: shows the next AI-generated image + caption and lets
// the founder approve (schedule it) or regenerate, in one click.
export function NextPost({
  post,
  onChange,
}: {
  post: NextPostType | null;
  onChange: () => Promise<void> | void;
}) {
  const [busy, setBusy] = useState<"approve" | "regen" | null>(null);
  const [imgError, setImgError] = useState(false);

  const run = async (key: "approve" | "regen", fn: () => Promise<unknown>) => {
    if (busy) return;
    setBusy(key);
    try {
      await fn();
      setImgError(false);
      await onChange();
    } finally {
      setBusy(null);
    }
  };

  return (
    <section className="panel flex h-full flex-col">
      <header className="panel-header">
        <div className="flex items-center gap-2">
          <Send className="h-4 w-4 text-hud-emerald" strokeWidth={1.6} />
          <h2 className="text-sm font-medium text-slate-200">Next Post</h2>
        </div>
        {post && (
          <span className="hud-label">{post.target.replace("_", " ")}</span>
        )}
      </header>

      <div className="flex flex-1 flex-col gap-3 p-3">
        <div className="relative aspect-square w-full overflow-hidden rounded-lg border border-edge bg-panel-2">
          {post && !imgError ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={post.image_url}
              alt="Next post creative"
              className="h-full w-full object-cover"
              onError={() => setImgError(true)}
            />
          ) : (
            <div className="flex h-full w-full flex-col items-center justify-center gap-2 text-slate-600">
              <ImageOff className="h-7 w-7" />
              <span className="text-[10px]">{post ? "Image loading…" : "No draft yet"}</span>
            </div>
          )}
          <span className="absolute left-2 top-2 rounded bg-black/60 px-1.5 py-0.5 text-[9px] uppercase tracking-wide text-hud-cyan">
            free AI image
          </span>
        </div>

        <p className="scroll-thin max-h-24 overflow-y-auto whitespace-pre-line text-[11px] leading-relaxed text-slate-300">
          {post ? post.caption : "Generating your next post…"}
        </p>

        {post && (
          <div className="text-[10px] text-slate-600">
            Posts to: <span className="text-slate-400">{post.channels.join(", ")}</span>
          </div>
        )}

        <div className="mt-auto grid grid-cols-2 gap-2">
          <button
            onClick={() => run("approve", () => api.approveNextPost())}
            disabled={!post || busy !== null}
            className="flex items-center justify-center gap-1.5 rounded-lg border border-hud-emerald/40 bg-hud-emerald/5 px-3 py-2 text-xs text-hud-emerald transition-colors hover:bg-hud-emerald/10 disabled:opacity-50"
          >
            <CheckCircle2 className={`h-3.5 w-3.5 ${busy === "approve" ? "animate-pulseGlow" : ""}`} />
            {busy === "approve" ? "Scheduling…" : "Approve & schedule"}
          </button>
          <button
            onClick={() => run("regen", () => api.regenerateNextPost())}
            disabled={busy !== null}
            className="flex items-center justify-center gap-1.5 rounded-lg border border-edge bg-panel/80 px-3 py-2 text-xs text-slate-300 transition-colors hover:border-hud-cyan/40 hover:text-hud-cyan disabled:opacity-50"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${busy === "regen" ? "animate-spin" : ""}`} />
            {busy === "regen" ? "Working…" : "Regenerate"}
          </button>
        </div>
      </div>
    </section>
  );
}
