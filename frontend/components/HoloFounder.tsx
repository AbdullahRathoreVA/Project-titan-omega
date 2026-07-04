"use client";

// Wrapper for the holographic Founder: listens for the global "titan-speech"
// events from the voice layer and drives the 3D scene's speaking state via a
// ref (no re-renders per frame). Dynamic import + boundary keep it safe.

import { Component, useEffect, useRef, useState, type ReactNode } from "react";
import dynamic from "next/dynamic";

const Scene = dynamic(() => import("./HoloFounder3D"), { ssr: false, loading: () => null });

class Boundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    return this.state.failed ? null : this.props.children;
  }
}

export function HoloFounder() {
  const speakingRef = useRef(false);
  const [speaking, setSpeaking] = useState(false);

  useEffect(() => {
    const handler = (e: Event) => {
      const on = !!(e as CustomEvent).detail?.speaking;
      speakingRef.current = on;
      setSpeaking(on);
    };
    window.addEventListener("titan-speech", handler);
    return () => window.removeEventListener("titan-speech", handler);
  }, []);

  return (
    <div className="relative h-36 w-full overflow-hidden border-b border-edge/60">
      <Boundary>
        <Scene speakingRef={speakingRef} />
      </Boundary>
      <div className="pointer-events-none absolute left-3 top-2 hud-label">Titan Founder</div>
      <div
        className={`pointer-events-none absolute right-3 top-2 flex items-center gap-1.5 text-[10px] ${
          speaking ? "text-hud-cyan" : "text-slate-600"
        }`}
      >
        <span className={`h-1.5 w-1.5 rounded-full ${speaking ? "animate-pulseGlow bg-hud-cyan" : "bg-slate-700"}`} />
        {speaking ? "speaking" : "listening"}
      </div>
    </div>
  );
}
