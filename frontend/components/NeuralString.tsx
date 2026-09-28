"use client";

// Dynamic wrapper for the Neural String scene: ssr:false keeps the static
// export from rendering WebGL at build time, and the error boundary + CSS
// fallback cover weak devices and missing WebGL.

import { Component, type ReactNode } from "react";
import dynamic from "next/dynamic";

const Scene = dynamic(() => import("./NeuralString3D"), {
  ssr: false,
  loading: () => <Fallback />,
});

function Fallback() {
  return (
    <div className="flex h-full w-full items-center justify-center">
      <div className="relative h-44 w-44">
        <div className="absolute inset-0 animate-sweep rounded-full border border-hud-cyan/30" />
        <div className="absolute inset-6 animate-sweep rounded-full border border-hud-violet/30 [animation-direction:reverse]" />
        <div className="absolute inset-0 flex items-center justify-center">
          <div className="h-14 w-14 animate-pulseGlow rounded-full border border-hud-cyan/60 bg-panel-2 shadow-glow" />
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
    return this.state.failed ? <Fallback /> : this.props.children;
  }
}

export function NeuralString({ intensity, count }: { intensity: number; count?: number }) {
  return (
    <Boundary>
      <Scene intensity={intensity} count={count} />
    </Boundary>
  );
}
