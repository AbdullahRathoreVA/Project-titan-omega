"use client";

// Wrapper around the WebGL scene: dynamic import (ssr:false) keeps the static
// export from rendering WebGL at build time, and the error boundary + CSS core
// show something on weak devices or when WebGL is unavailable.

import { Component, type ReactNode } from "react";
import dynamic from "next/dynamic";

const Scene = dynamic(() => import("./TitanCore3D"), {
  ssr: false,
  loading: () => <CoreFallback label="Booting core…" />,
});

function CoreFallback({ label = "Core" }: { label?: string }) {
  return (
    <div className="flex h-full w-full items-center justify-center">
      <div className="relative h-40 w-40">
        <div className="absolute inset-0 rounded-full border border-edge" />
        <div className="absolute inset-0 animate-sweep rounded-full border-t-2 border-hud-cyan" />
        <div className="absolute inset-4 animate-sweep rounded-full border-b-2 border-hud-violet [animation-direction:reverse]" />
        <div className="absolute inset-0 flex items-center justify-center">
          <div className="flex h-16 w-16 animate-pulseGlow items-center justify-center rounded-full border border-hud-cyan/60 bg-panel-2 shadow-glow">
            <span className="font-mono text-[10px] text-hud-cyan">{label}</span>
          </div>
        </div>
      </div>
    </div>
  );
}

class Boundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    return this.state.failed ? <CoreFallback label="Core" /> : this.props.children;
  }
}

export function TitanCore({ intensity }: { intensity: number }) {
  return (
    <Boundary>
      <Scene intensity={intensity} />
    </Boundary>
  );
}
