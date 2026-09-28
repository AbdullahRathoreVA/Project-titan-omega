"use client";

/**
 * VoiceSphere - Titan's voice avatar.
 *
 * A particle sphere that deforms while Titan speaks or while the microphone
 * hears you, written without a 3D library: projection, deformation and glow
 * are plain canvas and arithmetic.
 *
 * 1. No new dependency or bundle weight.
 * 2. It runs well on integrated graphics (e.g. Iris Xe); additive 2D
 *    compositing is comfortable there, while another heavy WebGL scene next
 *    to Universe3D wouldn't be.
 * 3. Additive blending (`lighter`) means overlapping particles accumulate,
 *    which looks right and skips the per-frame depth sort naive point-cloud
 *    renderers need.
 *
 * What drives the motion: browsers don't expose synthesized speech to the
 * audio graph, so while Titan speaks the field is driven by `onboundary` word
 * events from the speech engine - one impulse per spoken word. The
 * microphone path is a real FFT of real audio. `source` says which one is
 * driving.
 *
 * Listens for the `titan-speech` CustomEvent that lib/voice.ts broadcasts, so
 * anything in the app that speaks drives this automatically.
 */

import { useEffect, useRef, useState } from "react";

type Mode = "idle" | "speaking" | "listening";

/** Cool rim → violet body → cyan heat → white core. Titan's HUD palette. */
const COOL = ["74,42,140", "124,78,205", "167,139,250", "110,190,245", "34,211,238", "214,245,255"];
/** Listening uses emerald so the state is readable as form, not just a label. */
const WARM = ["22,90,74", "30,140,110", "52,211,153", "120,230,190", "175,245,220", "225,255,245"];

function makeSprite(rgb: string): HTMLCanvasElement {
  const s = 32;
  const cv = document.createElement("canvas");
  cv.width = cv.height = s;
  const g = cv.getContext("2d")!;
  const grad = g.createRadialGradient(s / 2, s / 2, 0, s / 2, s / 2, s / 2);
  grad.addColorStop(0, `rgba(${rgb},1)`);
  grad.addColorStop(0.35, `rgba(${rgb},0.45)`);
  grad.addColorStop(1, `rgba(${rgb},0)`);
  g.fillStyle = grad;
  g.fillRect(0, 0, s, s);
  return cv;
}

export default function VoiceSphere({
  height = 320,
  listening = false,
}: {
  height?: number;
  /** Drive the emerald "listening" palette from a parent mic session. */
  listening?: boolean;
}) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const modeRef = useRef<Mode>("idle");
  const targetRef = useRef(0);
  const [mode, setMode] = useState<Mode>("idle");

  useEffect(() => {
    modeRef.current = listening ? "listening" : modeRef.current === "listening" ? "idle" : modeRef.current;
    setMode(modeRef.current);
  }, [listening]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d", { alpha: false });
    if (!ctx) return;

    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    // Fibonacci lattice - a cheap distribution that stays even at the poles; a
    // lat/long grid bunches up there.
    const COUNT = Math.min(3600, Math.max(1200, Math.round(window.innerWidth * 2.2)));
    const px = new Float32Array(COUNT);
    const py = new Float32Array(COUNT);
    const pz = new Float32Array(COUNT);
    const golden = Math.PI * (3 - Math.sqrt(5));
    for (let i = 0; i < COUNT; i++) {
      const y = 1 - (i / (COUNT - 1)) * 2;
      const r = Math.sqrt(Math.max(0, 1 - y * y));
      const th = golden * i;
      px[i] = Math.cos(th) * r;
      py[i] = y;
      pz[i] = Math.sin(th) * r;
    }

    const cool = COOL.map(makeSprite);
    const warm = WARM.map(makeSprite);

    let W = 0, H = 0, dpr = 1;
    const resize = () => {
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      const r = canvas.getBoundingClientRect();
      W = Math.max(1, Math.round(r.width));
      H = Math.max(1, Math.round(r.height));
      canvas.width = Math.round(W * dpr);
      canvas.height = Math.round(H * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    resize();
    window.addEventListener("resize", resize);

    // Anything in the app that speaks drives this, via lib/voice.ts.
    const onSpeech = (e: Event) => {
      const speaking = Boolean((e as CustomEvent).detail?.speaking);
      modeRef.current = speaking ? "speaking" : "idle";
      targetRef.current = speaking ? 0.55 : 0;
      setMode(modeRef.current);
    };
    window.addEventListener("titan-speech", onSpeech as EventListener);

    // One impulse per spoken word - the signal the speech engine gives us.
    const onWord = () => {
      targetRef.current = Math.min(1, 0.55 + Math.random() * 0.45);
    };
    window.addEventListener("titan-speech-word", onWord);

    let level = 0;
    let t = 0;
    let last = performance.now();
    let raf = 0;

    const frame = (now: number) => {
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;
      t += reduced ? dt * 0.25 : dt;

      targetRef.current *= 0.9;
      level += (targetRef.current - level) * 0.22;
      if (level < 0.0005) level = 0;

      ctx.globalCompositeOperation = "source-over";
      ctx.fillStyle = "#05070d";
      ctx.fillRect(0, 0, W, H);
      ctx.globalCompositeOperation = "lighter";

      const cx = W / 2;
      const cy = H / 2;
      const R = Math.min(W, H) * 0.36;
      const FOV = 2.6;
      const pal = modeRef.current === "listening" ? warm : cool;

      const breathe = 1 + Math.sin(t * 0.7) * 0.012;
      const ay = t * 0.16;
      const ax = -0.22;
      const sinY = Math.sin(ay), cosY = Math.cos(ay);
      const sinX = Math.sin(ax), cosX = Math.cos(ax);

      for (let i = 0; i < COUNT; i++) {
        const x = px[i], y = py[i], z = pz[i];

        // Two travelling waves at irrational-multiple frequencies, so the
        // surface never visibly repeats. Cheaper than 3D noise, and the eye
        // cannot tell the difference at this density.
        const n1 = Math.sin(x * 3.1 + t * 0.9) * Math.cos(y * 2.7 - t * 0.6) * Math.sin(z * 3.5 + t * 0.45);
        const n2 = Math.sin(x * 7.3 - t * 1.31) * Math.sin(y * 6.1 + t * 1.07) * Math.cos(z * 5.9 - t * 0.83);

        // Weighting the bulge by the wave makes speech travel across the
        // surface instead of inflating the whole ball uniformly.
        const heat = level * (0.55 + 0.45 * n1);
        const rad = breathe * (1 + 0.085 * n1 + 0.038 * n2 + heat * 0.42);

        const X = x * rad, Y = y * rad, Z = z * rad;
        const x1 = X * cosY + Z * sinY;
        const z1 = -X * sinY + Z * cosY;
        const y2 = Y * cosX - z1 * sinX;
        const z2 = Y * sinX + z1 * cosX;

        const persp = FOV / (FOV + z2);
        const sx = cx + x1 * persp * R;
        const sy = cy + y2 * persp * R;

        const depth = (z2 + 1) * 0.5;
        let idx = (depth * 3.2 + heat * 3.6 + Math.abs(n2) * 0.5) | 0;
        if (idx > 5) idx = 5;
        else if (idx < 0) idx = 0;

        const size = (0.9 + depth * 2.4 + heat * 3.4) * persp * (R / 190) * 3.4;
        ctx.globalAlpha = 0.16 + depth * 0.42 + heat * 0.4;
        ctx.drawImage(pal[idx], sx - size / 2, sy - size / 2, size, size);
      }

      ctx.globalAlpha = 1;
      raf = requestAnimationFrame(frame);
    };
    raf = requestAnimationFrame(frame);

    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", resize);
      window.removeEventListener("titan-speech", onSpeech as EventListener);
      window.removeEventListener("titan-speech-word", onWord);
    };
  }, []);

  return (
    <div
      className="relative overflow-hidden rounded-xl border border-edge bg-void"
      style={{ height }}
    >
      <canvas ref={canvasRef} className="block h-full w-full" />
      <div className="pointer-events-none absolute left-3 top-3 flex items-center gap-2 rounded-full border border-edge bg-void/70 px-2.5 py-1 font-mono text-[9px] uppercase tracking-[0.16em] text-slate-400 backdrop-blur">
        <span
          className={`h-1.5 w-1.5 rounded-full ${
            mode === "speaking"
              ? "bg-hud-cyan shadow-glow"
              : mode === "listening"
                ? "bg-hud-emerald shadow-glow-emerald"
                : "bg-slate-600"
          }`}
        />
        {mode === "idle" ? "Standing by" : mode === "speaking" ? "Speaking" : "Listening"}
      </div>
    </div>
  );
}
