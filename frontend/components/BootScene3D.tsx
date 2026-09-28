"use client";

// Boot sequence 3D scene: thousands of glowing particles fly in from a chaos
// sphere and assemble into "TITAN Ω / HELLO ABDULLAH", then the camera
// flies straight through the text into the dashboard. Text pixels are sampled
// from an offscreen canvas so the letters literally form from light.

import { useMemo, useRef } from "react";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { Stars } from "@react-three/drei";
import { EffectComposer, Bloom } from "@react-three/postprocessing";
import * as THREE from "three";
import { isCoarsePointer } from "@/lib/device";
import { isGuest } from "@/lib/guest";
import { displayName, isCustomer, isDemo } from "@/lib/session";

/** The founder is greeted by name; a subscriber by theirs; a demo visitor
 *  by nobody's. (The demo used to be greeted as ABDULLAH too.) */
function greeting(): string {
  if (isGuest() || isDemo()) return "WELCOME";
  if (isCustomer()) return `HELLO ${displayName().toUpperCase()}`.slice(0, 22);
  return "HELLO ABDULLAH";
}

function sampleTextPoints(): Float32Array {
  const W = 960;
  const H = 260;
  const c = document.createElement("canvas");
  c.width = W;
  c.height = H;
  const g = c.getContext("2d");
  if (!g) return new Float32Array(0);
  g.fillStyle = "#fff";
  g.textAlign = "center";
  g.textBaseline = "middle";
  g.font = "bold 96px 'Segoe UI', monospace";
  g.fillText("TITAN Ω", W / 2, 78);
  g.font = "bold 44px 'Segoe UI', monospace";
  g.fillText(greeting(), W / 2, 195);
  const data = g.getImageData(0, 0, W, H).data;
  const pts: number[] = [];
  for (let y = 0; y < H; y += 3) {
    for (let x = 0; x < W; x += 3) {
      if (data[(y * W + x) * 4 + 3] > 128) {
        pts.push((x - W / 2) / 62, -(y - H / 2) / 62, 0);
      }
    }
  }
  return new Float32Array(pts);
}

function easeInOut(t: number): number {
  return t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;
}

function ParticleText() {
  const geom = useRef<THREE.BufferGeometry>(null);
  const { camera } = useThree();

  const { targets, starts, count } = useMemo(() => {
    const t = sampleTextPoints();
    const n = t.length / 3;
    const s = new Float32Array(t.length);
    for (let i = 0; i < n; i++) {
      // chaos sphere start positions
      const r = 9 + Math.random() * 8;
      const theta = Math.random() * Math.PI * 2;
      const phi = Math.acos(2 * Math.random() - 1);
      s[i * 3] = r * Math.sin(phi) * Math.cos(theta);
      s[i * 3 + 1] = r * Math.sin(phi) * Math.sin(theta);
      s[i * 3 + 2] = r * Math.cos(phi) - 4;
    }
    return { targets: t, starts: s, count: n };
  }, []);

  const positions = useMemo(() => new Float32Array(starts), [starts]);

  useFrame(({ clock }) => {
    const t = clock.getElapsedTime();
    const attr = geom.current?.attributes.position as THREE.BufferAttribute | undefined;
    if (!attr) return;

    // 0.6s → 4.2s: particles converge onto the text, staggered per particle.
    const arr = attr.array as Float32Array;
    for (let i = 0; i < count; i++) {
      const stagger = (i % 100) / 100;
      const p = Math.min(1, Math.max(0, (t - 0.6 - stagger * 0.9) / 2.7));
      const e = easeInOut(p);
      const jitter = (1 - e) * 0.08;
      arr[i * 3] = starts[i * 3] + (targets[i * 3] - starts[i * 3]) * e + (Math.random() - 0.5) * jitter;
      arr[i * 3 + 1] = starts[i * 3 + 1] + (targets[i * 3 + 1] - starts[i * 3 + 1]) * e + (Math.random() - 0.5) * jitter;
      arr[i * 3 + 2] = starts[i * 3 + 2] + (targets[i * 3 + 2] - starts[i * 3 + 2]) * e;
    }
    attr.needsUpdate = true;

    // 4.6s+: fly the camera through the text into the digital universe.
    if (t > 4.6) {
      camera.position.z = Math.max(-4, 11 - (t - 4.6) * 6.5);
      camera.position.y = (t - 4.6) * 0.25;
    }
  });

  return (
    <points>
      <bufferGeometry ref={geom}>
        <bufferAttribute attach="attributes-position" count={count} array={positions} itemSize={3} />
      </bufferGeometry>
      <pointsMaterial size={0.045} color="#4de3ff" transparent opacity={0.95} sizeAttenuation depthWrite={false} />
    </points>
  );
}

function EnergyRing() {
  const ref = useRef<THREE.Mesh>(null);
  useFrame(({ clock }) => {
    const t = clock.getElapsedTime();
    if (ref.current) {
      ref.current.rotation.z = t * 0.4;
      const s = 1 + Math.sin(t * 2) * 0.04;
      ref.current.scale.set(s, s, s);
    }
  });
  return (
    <mesh ref={ref} position={[0, 0, -2]}>
      <torusGeometry args={[5.2, 0.015, 8, 128]} />
      <meshBasicMaterial color="#a78bfa" transparent opacity={0.5} />
    </mesh>
  );
}

export default function BootScene3D() {
  // Phones: fewer stars, no post-processing — keeps the boot smooth everywhere.
  const mobile = useMemo(() => isCoarsePointer(), []);
  return (
    <Canvas camera={{ position: [0, 0, 11], fov: 55 }} dpr={[1, mobile ? 1.2 : 1.5]} gl={{ antialias: !mobile }}>
      <color attach="background" args={["#020409"]} />
      <Stars radius={70} depth={50} count={mobile ? 1100 : 2200} factor={3.2} fade speed={1.4} />
      <ParticleText />
      <EnergyRing />
      {!mobile && (
        <EffectComposer>
          <Bloom intensity={1.1} luminanceThreshold={0.15} luminanceSmoothing={0.9} mipmapBlur />
        </EffectComposer>
      )}
    </Canvas>
  );
}
