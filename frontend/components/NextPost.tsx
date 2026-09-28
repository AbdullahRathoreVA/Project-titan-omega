"use client";

import { useEffect, useRef, useState } from "react";
import { CheckCircle2, ImageOff, RefreshCw, Send } from "lucide-react";
import type { NextPost as NextPostType } from "@/lib/types";
import { api } from "@/lib/api";
import { isCustomer } from "@/lib/session";

type ApproveResult = { sent?: boolean; channels?: string[] };
type Outcome = { sent: boolean; channels: string[]; refused?: boolean };

// The HUD "Next Post" card: shows the next AI-generated image + caption and lets
// the founder approve (schedule it) or regenerate, in one click. Fresh AI images
// can take 30-60s to generate server-side, so a failed load auto-retries with
// backoff instead of sticking on a broken frame.
export function NextPost({
  post,
  onChange,
}: {
  post: NextPostType | null;
  onChange: () => Promise<void> | void;
}) {
  const [busy, setBusy] = useState<"approve" | "regen" | null>(null);
  const [result, setResult] = useState<Outcome | null>(null);
  const [imgError, setImgError] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const retryTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // New post → reset the image retry cycle.
  useEffect(() => {
    setImgError(false);
    setAttempt(0);
    return () => {
      if (retryTimer.current) clearTimeout(retryTimer.current);
    };
  }, [post?.id]);

  const handleImgError = () => {
    if (attempt < 3) {
      // The generator is probably still rendering — try again shortly.
      retryTimer.current = setTimeout(() => setAttempt((a) => a + 1), 6000 + attempt * 6000);
    } else {
      setImgError(true);
    }
  };

  const retryImage = () => {
    setImgError(false);
    setAttempt((a) => a + 1);
  };

  const run = async (key: "approve" | "regen", fn: () => Promise<unknown>) => {
    if (busy) return;
    setBusy(key);
    setResult(null);
    try {
      const out = await fn();
      // Approving must report what actually happened. Clicking a button and
      // seeing nothing change is why this looked broken.
      if (key === "approve") {
        const r = out as ApproveResult | null;
        // No answer means nothing was scheduled - not "saved to the queue".
        setResult(r ? { sent: Boolean(r.sent), channels: r.channels ?? [] }
                    : { sent: false, channels: [], refused: true });
      }
      setImgError(false);
      setAttempt(0);
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

      <div className="flex min-h-0 flex-1 flex-col gap-3 p-3">
        {/* flex-1 + min-h-0 (NOT aspect-square): the image yields space so the
            caption and buttons always fit INSIDE the fixed-height card. */}
        <div className="relative min-h-[120px] w-full flex-1 overflow-hidden rounded-lg border border-edge bg-panel-2">
          {post?.unavailable ? (
            // A placeholder has no image; saying it is "still rendering"
            // would promise one that is never coming.
            <div className="flex h-full w-full items-center justify-center text-slate-600">
              <ImageOff className="h-7 w-7" />
            </div>
          ) : post && !imgError ? (
            // key forces a fresh load attempt; the URL is stable so once the
            // generator finishes, the retry hits its cache and renders.
            // eslint-disable-next-line @next/next/no-img-element
            <img
              key={`${post.id}-${attempt}`}
              src={post.image_url}
              alt="Next post creative"
              className="h-full w-full object-cover"
              onError={handleImgError}
            />
          ) : (
            <div className="flex h-full w-full flex-col items-center justify-center gap-2 text-slate-600">
              <ImageOff className="h-7 w-7" />
              <span className="text-[10px]">
                {post ? "Image still rendering (AI images take up to a minute)" : "No draft yet"}
              </span>
              {post && (
                <button
                  onClick={retryImage}
                  className="rounded border border-edge px-2 py-1 text-[10px] text-slate-400 hover:border-hud-cyan/40 hover:text-hud-cyan"
                >
                  Retry image
                </button>
              )}
            </div>
          )}
          <span className="absolute left-2 top-2 rounded bg-black/60 px-1.5 py-0.5 text-[9px] uppercase tracking-wide text-hud-cyan">
            free AI image
          </span>
        </div>

        {/* No height cap. `max-h-16` was 64px, which clipped a normal caption
          mid-URL on a 1920px desktop and hid the link the post is FOR — the
          one part that has to be checked before approving. The page scrolls;
          the caption does not need its own scrollbar. */}
      <p className="shrink-0 whitespace-pre-line break-words text-[11px] leading-relaxed text-slate-300">
          {post ? post.caption : "Generating your next post…"}
        </p>

        {/* This used to read "Posts to: linkedin, instagram, facebook"
            regardless of whether any of them could be reached. Nothing was
            connected, so approving sent nothing while the card said it would
            — a button that appears to work and does not is worse than one
            that is plainly disabled. */}
        {post && (
          post.publish?.ready ? (
            <div className="shrink-0 text-[10px] text-slate-600">
              Posts to: <span className="text-slate-400">{post.channels.join(", ")}</span>
            </div>
          ) : (
            <div className="shrink-0 rounded-lg border border-hud-amber/30 bg-hud-amber/5 px-2.5 py-2 text-[10px] leading-relaxed text-hud-amber">
              <span className="font-semibold">Nothing will be sent yet.</span>{" "}
              {post.publish?.reason ??
                "No publishing route is connected — approving saves the post to the queue."}
            </div>
          )
        )}

        {result && (
          <div
            className={`shrink-0 rounded-lg border px-2.5 py-2 text-[10px] leading-relaxed ${
              result.sent
                ? "border-hud-emerald/30 bg-hud-emerald/5 text-hud-emerald"
                : "border-hud-amber/30 bg-hud-amber/5 text-hud-amber"
            }`}
          >
            {result.refused
              ? "Nothing was scheduled. Try again, or press Regenerate for a fresh draft."
              : result.sent
              ? `Sent to ${result.channels.join(", ")}.`
              : isCustomer()
                ? "Saved to your queue with its caption and image. Titan does not post for you — copy it to your channels."
                : "Saved to the queue with its caption and image. It was not sent — connect a publishing route first."}
          </div>
        )}

        <div className="grid shrink-0 grid-cols-2 gap-2">
          <button
            onClick={() => run("approve", () => api.approveNextPost())}
            disabled={!post || Boolean(post.unavailable) || busy !== null}
            className="flex items-center justify-center gap-1.5 rounded-lg border border-hud-emerald/40 bg-hud-emerald/5 px-3 py-2 text-xs text-hud-emerald transition-colors hover:bg-hud-emerald/10 disabled:opacity-50"
          >
            <CheckCircle2 className={`h-3.5 w-3.5 ${busy === "approve" ? "animate-pulseGlow" : ""}`} />
            {busy === "approve" ? "Scheduling…" : "Approve & schedule"}
          </button>
          <button
            onClick={() => run("regen", () => api.regenerateNextPost())}
            // Regenerating helps when the AI was down, not in the demo or
            // before there is a business to write about.
            disabled={busy !== null || post?.unavailable === "demo"
              || post?.unavailable === "no_business"}
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
