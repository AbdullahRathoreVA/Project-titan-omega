"use client";

// The 3D centerpiece: a wireframe core globe with an orbiting agent-network of
// nodes, drifting in a starfield. Rotation speed + glow scale with the live
// activity "intensity" pushed by the SSE stream — so the empire visibly speeds
// up as agents work and money lands. Loaded via next/dynamic (ssr:false) by
// TitanCore.tsx so the static export never tries to render WebGL at build time.

import { useMemo, useRef } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import { Float, Stars } from "@react-three/drei";
import * as THREE from "three";

const NODE_COLORS = ["#22d3ee", "#a78bfa", "#34d399", "#fbbf24", "#fb7185", "#3b82f6"];

function Nodes({ intensity }: { intensity: number }) {
  // Fibonacci-sphere distribution so nodes spread evenly around the core.
  const nodes = useMemo(() => {
    const out: { pos: [number, number, number]; color: string }[] = [];
    const n = 20;
    const golden = Math.PI * (1 + Math.sqrt(5));
    for (let i = 0; i < n; i++) {
      const y = 1 - (i / (n - 1)) * 2;
      const r = Math.sqrt(1 - y * y) * 1.95;
      const theta = golden * i;
      out.push({
        pos: [Math.cos(theta) * r, y * 1.95, Math.sin(theta) * r],
        color: NODE_COLORS[i % NODE_COLORS.length],
      });
    }
    return out;
  }, []);

  return (
    <>
      {nodes.map((nd, i) => (
        <mesh key={i} position={nd.pos}>
          <sphereGeometry args={[0.07, 14, 14]} />
          <meshStandardMaterial
            color={nd.color}
            emissive={nd.color}
            emissiveIntensity={0.7 + intensity}
          />
        </mesh>
      ))}
    </>
  );
}

function Core({ intensity }: { intensity: number }) {
  const group = useRef<THREE.Group>(null);
  const iref = useRef(intensity);
  iref.current = intensity;

  useFrame((_, dt) => {
    if (group.current) group.current.rotation.y += dt * (0.12 + iref.current * 0.7);
  });

  return (
    <group ref={group}>
      <mesh>
        <icosahedronGeometry args={[1.65, 1]} />
        <meshBasicMaterial color="#22d3ee" wireframe transparent opacity={0.28} />
      </mesh>
      <mesh>
        <icosahedronGeometry args={[1.3, 2]} />
        <meshBasicMaterial color="#a78bfa" wireframe transparent opacity={0.16} />
      </mesh>
      <mesh>
        <sphereGeometry args={[0.55, 32, 32]} />
        <meshStandardMaterial
          color="#0d1322"
          emissive="#22d3ee"
          emissiveIntensity={0.5 + intensity * 1.2}
          roughness={0.3}
          metalness={0.6}
        />
      </mesh>
      <Nodes intensity={intensity} />
    </group>
  );
}

export default function TitanCore3D({ intensity = 0.4 }: { intensity?: number }) {
  return (
    <Canvas camera={{ position: [0, 0, 5.2], fov: 50 }} dpr={[1, 1.5]} gl={{ antialias: true }}>
      <ambientLight intensity={0.5} />
      <pointLight position={[5, 5, 5]} intensity={1.3} color="#22d3ee" />
      <pointLight position={[-5, -3, -2]} intensity={0.9} color="#a78bfa" />
      <Stars radius={60} depth={35} count={1400} factor={3} fade speed={1} />
      <Float speed={1.6} rotationIntensity={0.35} floatIntensity={0.5}>
        <Core intensity={intensity} />
      </Float>
    </Canvas>
  );
}
