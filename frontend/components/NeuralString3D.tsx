"use client";

// Titan's unique 3D signature: a living "neural string" web — glowing curved
// strings run from a central app-core out to orbiting agent nodes, the whole
// lattice rotating and pulsing with live activity intensity. Loaded via
// next/dynamic (ssr:false) so the static export never renders WebGL at build.

import { useMemo, useRef } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import { Float, QuadraticBezierLine, Stars } from "@react-three/drei";
import * as THREE from "three";

const COLORS = ["#22d3ee", "#a78bfa", "#34d399", "#fbbf24", "#fb7185", "#3b82f6"];

function Web({ intensity, count }: { intensity: number; count: number }) {
  const group = useRef<THREE.Group>(null);
  const iref = useRef(intensity);
  iref.current = intensity;

  const nodes = useMemo(() => {
    const n = Math.max(8, Math.min(count || 12, 18));
    const golden = Math.PI * (1 + Math.sqrt(5));
    const arr: { pos: [number, number, number]; mid: [number, number, number]; color: string }[] = [];
    for (let i = 0; i < n; i++) {
      const y = 1 - (i / (n - 1)) * 2;
      const r = Math.sqrt(Math.max(0, 1 - y * y)) * 2.15;
      const theta = golden * i;
      const pos: [number, number, number] = [Math.cos(theta) * r, y * 2.15, Math.sin(theta) * r];
      const mid: [number, number, number] = [pos[0] * 0.45, pos[1] * 0.45 + 0.35, pos[2] * 0.45];
      arr.push({ pos, mid, color: COLORS[i % COLORS.length] });
    }
    return arr;
  }, [count]);

  useFrame((_, dt) => {
    if (group.current) group.current.rotation.y += dt * (0.1 + iref.current * 0.55);
  });

  return (
    <group ref={group}>
      <mesh>
        <icosahedronGeometry args={[0.62, 1]} />
        <meshStandardMaterial color="#0d1322" emissive="#22d3ee" emissiveIntensity={0.6 + intensity} wireframe />
      </mesh>
      <mesh>
        <sphereGeometry args={[0.34, 32, 32]} />
        <meshStandardMaterial color="#0d1322" emissive="#22d3ee" emissiveIntensity={1 + intensity} roughness={0.3} metalness={0.6} />
      </mesh>
      {nodes.map((nd, i) => (
        <group key={i}>
          <QuadraticBezierLine
            start={[0, 0, 0]}
            mid={nd.mid}
            end={nd.pos}
            color={nd.color}
            lineWidth={1.1}
            transparent
            opacity={0.45 + intensity * 0.4}
          />
          <mesh position={nd.pos}>
            <sphereGeometry args={[0.085, 16, 16]} />
            <meshStandardMaterial color={nd.color} emissive={nd.color} emissiveIntensity={0.8 + intensity} />
          </mesh>
        </group>
      ))}
    </group>
  );
}

export default function NeuralString3D({
  intensity = 0.4,
  count = 14,
}: {
  intensity?: number;
  count?: number;
}) {
  return (
    <Canvas camera={{ position: [0, 0, 6], fov: 50 }} dpr={[1, 1.5]} gl={{ antialias: true }}>
      <ambientLight intensity={0.5} />
      <pointLight position={[5, 5, 5]} intensity={1.2} color="#22d3ee" />
      <pointLight position={[-5, -3, -2]} intensity={0.85} color="#a78bfa" />
      <Stars radius={60} depth={40} count={1600} factor={3} fade speed={1} />
      <Float speed={1.4} rotationIntensity={0.3} floatIntensity={0.5}>
        <Web intensity={intensity} count={count} />
      </Float>
    </Canvas>
  );
}
