"use client";

// A subtle full-viewport 3D field that sits behind the entire dashboard, so the
// whole app reads as a living 3D space — not just the core/lattice. Kept light
// (sparse points, capped dpr, low opacity) so panels stay readable and weak
// devices cope. Loaded via next/dynamic (ssr:false) by Background.tsx.

import { useMemo, useRef } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import * as THREE from "three";

function Field({ color, count, spread }: { color: string; count: number; spread: number }) {
  const ref = useRef<THREE.Points>(null);
  const positions = useMemo(() => {
    const a = new Float32Array(count * 3);
    for (let i = 0; i < count * 3; i++) a[i] = (Math.random() - 0.5) * spread;
    return a;
  }, [count, spread]);

  useFrame((_, dt) => {
    if (ref.current) {
      ref.current.rotation.y += dt * 0.02;
      ref.current.rotation.x += dt * 0.006;
    }
  });

  return (
    <points ref={ref}>
      <bufferGeometry>
        <bufferAttribute attach="attributes-position" count={count} array={positions} itemSize={3} />
      </bufferGeometry>
      <pointsMaterial size={0.035} color={color} transparent opacity={0.55} sizeAttenuation depthWrite={false} />
    </points>
  );
}

export default function Background3D() {
  return (
    <Canvas
      camera={{ position: [0, 0, 6], fov: 65 }}
      dpr={[1, 1.25]}
      gl={{ antialias: false, alpha: true }}
      style={{ position: "fixed", inset: 0, zIndex: -1, pointerEvents: "none" }}
    >
      <Field color="#22d3ee" count={900} spread={18} />
      <Field color="#a78bfa" count={500} spread={22} />
    </Canvas>
  );
}
