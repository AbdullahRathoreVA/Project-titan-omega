"use client";

// The holographic founder projected from an emitter base: a particle bust
// (head + shoulders) with scan rings and a light beam. It breathes when idle
// and flares while Titan speaks (driven by the global "titan-speech" events
// from the voice layer).

import { useMemo, useRef } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import * as THREE from "three";
import { isCoarsePointer } from "@/lib/device";

function fib(n: number, cb: (x: number, y: number, z: number, i: number) => void) {
  const golden = Math.PI * (1 + Math.sqrt(5));
  for (let i = 0; i < n; i++) {
    const y = 1 - (i / (n - 1)) * 2;
    const r = Math.sqrt(Math.max(0, 1 - y * y));
    const t = golden * i;
    cb(Math.cos(t) * r, y, Math.sin(t) * r, i);
  }
}

function Bust({ speakingRef }: { speakingRef: React.MutableRefObject<boolean> }) {
  const group = useRef<THREE.Group>(null);
  const mat = useRef<THREE.PointsMaterial>(null);

  const { positions, base, count } = useMemo(() => {
    const pts: number[] = [];
    // Head: full particle sphere.
    fib(420, (x, y, z) => pts.push(x * 0.42, y * 0.42 + 1.28, z * 0.42));
    // Shoulders/torso: lower half-ellipsoid, wider than the head.
    fib(520, (x, y, z) => {
      if (y < 0.15) pts.push(x * 0.85, y * 0.55 + 0.72, z * 0.62);
    });
    const arr = new Float32Array(pts);
    return { positions: arr, base: new Float32Array(arr), count: arr.length / 3 };
  }, []);

  const geom = useRef<THREE.BufferGeometry>(null);

  useFrame(({ clock }) => {
    const t = clock.getElapsedTime();
    const speaking = speakingRef.current;
    if (group.current) group.current.rotation.y = t * 0.35;

    // Particle shimmer: gentle breathing idle; energetic jitter while speaking.
    const attr = geom.current?.attributes.position as THREE.BufferAttribute | undefined;
    if (attr) {
      const arr = attr.array as Float32Array;
      const amp = speaking ? 0.035 : 0.008;
      const speed = speaking ? 9 : 2.2;
      for (let i = 0; i < count; i++) {
        const phase = i * 0.7;
        arr[i * 3] = base[i * 3] + Math.sin(t * speed + phase) * amp;
        arr[i * 3 + 1] = base[i * 3 + 1] + Math.cos(t * speed * 0.8 + phase) * amp;
        arr[i * 3 + 2] = base[i * 3 + 2] + Math.sin(t * speed * 1.1 + phase * 1.3) * amp;
      }
      attr.needsUpdate = true;
    }
    if (mat.current) {
      mat.current.opacity = speaking ? 0.95 : 0.65 + Math.sin(t * 1.4) * 0.08;
      mat.current.size = speaking ? 0.05 : 0.038;
    }
  });

  return (
    <group ref={group}>
      <points>
        <bufferGeometry ref={geom}>
          <bufferAttribute attach="attributes-position" count={count} array={positions} itemSize={3} />
        </bufferGeometry>
        <pointsMaterial
          ref={mat}
          size={0.038}
          color="#4de3ff"
          transparent
          opacity={0.7}
          sizeAttenuation
          depthWrite={false}
          blending={THREE.AdditiveBlending}
        />
      </points>
    </group>
  );
}

function ScanRings({ speakingRef }: { speakingRef: React.MutableRefObject<boolean> }) {
  const r1 = useRef<THREE.Mesh>(null);
  const r2 = useRef<THREE.Mesh>(null);
  useFrame(({ clock }) => {
    const t = clock.getElapsedTime();
    const speaking = speakingRef.current;
    const speed = speaking ? 1.6 : 0.55;
    // Two rings sweep up the hologram like scan lines.
    [r1, r2].forEach((r, i) => {
      if (!r.current) return;
      const y = 0.3 + (((t * speed + i * 0.9) % 1.6) / 1.6) * 1.5;
      r.current.position.y = y;
      const s = 1 - Math.abs(y - 1.0) * 0.45;
      r.current.scale.set(s, s, s);
      (r.current.material as THREE.MeshBasicMaterial).opacity = speaking ? 0.5 : 0.22;
    });
  });
  return (
    <>
      {[r1, r2].map((r, i) => (
        <mesh key={i} ref={r} rotation={[Math.PI / 2, 0, 0]}>
          <torusGeometry args={[0.75, 0.008, 8, 64]} />
          <meshBasicMaterial color="#a78bfa" transparent opacity={0.25} />
        </mesh>
      ))}
    </>
  );
}

function Emitter({ speakingRef }: { speakingRef: React.MutableRefObject<boolean> }) {
  const beam = useRef<THREE.Mesh>(null);
  useFrame(({ clock }) => {
    if (beam.current) {
      const speaking = speakingRef.current;
      (beam.current.material as THREE.MeshBasicMaterial).opacity =
        (speaking ? 0.16 : 0.08) + Math.sin(clock.getElapsedTime() * 3) * 0.02;
    }
  });
  return (
    <group>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.02, 0]}>
        <ringGeometry args={[0.32, 0.55, 48]} />
        <meshBasicMaterial color="#22d3ee" transparent opacity={0.5} side={THREE.DoubleSide} />
      </mesh>
      <mesh ref={beam} position={[0, 0.95, 0]}>
        <coneGeometry args={[0.85, 1.9, 32, 1, true]} />
        <meshBasicMaterial color="#22d3ee" transparent opacity={0.09} side={THREE.DoubleSide} depthWrite={false} />
      </mesh>
    </group>
  );
}

export default function HoloFounder3D({
  speakingRef,
}: {
  speakingRef: React.MutableRefObject<boolean>;
}) {
  const mobile = useMemo(() => isCoarsePointer(), []);
  return (
    <Canvas camera={{ position: [0, 1.15, 3.1], fov: 42 }} dpr={[1, mobile ? 1.2 : 1.5]} gl={{ antialias: !mobile, alpha: true }}>
      <ambientLight intensity={0.6} />
      <pointLight position={[2, 3, 2]} intensity={0.8} color="#22d3ee" />
      <Bust speakingRef={speakingRef} />
      <ScanRings speakingRef={speakingRef} />
      <Emitter speakingRef={speakingRef} />
    </Canvas>
  );
}
