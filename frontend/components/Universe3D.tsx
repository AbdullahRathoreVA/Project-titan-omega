"use client";

// The Neural Command Universe — Titan's home view. An infinite living space:
// nebulas + star layers, an evolving central Core, the 12 real divisions as
// orbiting particle galaxies fed by colored energy streams, real metrics as
// floating holographic nodes, and comets that fire through the network on real
// feed activity. The camera never stops breathing; clicking flies you there.

import { useEffect, useMemo, useRef, useState } from "react";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { Html, QuadraticBezierLine, Stars } from "@react-three/drei";
import { EffectComposer, Bloom } from "@react-three/postprocessing";
import * as THREE from "three";
import { isCoarsePointer } from "@/lib/device";
import { blip } from "@/lib/sound";

export interface UniMetric {
  key: string;
  label: string;
  value: string;
  color: string;
}

export interface UniGalaxy {
  key: string;
  label: string;
  color: string;
  active: number;
  total: number;
}

export type UniSelection =
  | { type: "metric"; key: string }
  | { type: "galaxy"; key: string }
  | null;

export interface UniverseProps {
  metrics: UniMetric[];
  galaxies: UniGalaxy[];
  intensity: number;
  pulse: number; // increments on real feed activity → fires comets
  selected: UniSelection;
  onSelect: (sel: UniSelection) => void;
}

const GALAXY_R = 11;
const METRIC_R = 5.6;

function galaxyPos(i: number, n: number): [number, number, number] {
  const a = (i / Math.max(1, n)) * Math.PI * 2;
  return [Math.cos(a) * GALAXY_R, Math.sin(i * 2.1) * 1.6, Math.sin(a) * GALAXY_R];
}

function metricPos(i: number, n: number): [number, number, number] {
  const a = (i / Math.max(1, n)) * Math.PI * 2 + 0.4;
  return [Math.cos(a) * METRIC_R, 1.6 + Math.sin(i * 1.7) * 1.4, Math.sin(a) * METRIC_R];
}

// --- backdrop ---------------------------------------------------------------

function nebulaTexture(color: string): THREE.Texture {
  const c = document.createElement("canvas");
  c.width = c.height = 128;
  const g = c.getContext("2d")!;
  const grad = g.createRadialGradient(64, 64, 4, 64, 64, 64);
  grad.addColorStop(0, color);
  grad.addColorStop(1, "rgba(0,0,0,0)");
  g.fillStyle = grad;
  g.fillRect(0, 0, 128, 128);
  const tex = new THREE.CanvasTexture(c);
  return tex;
}

function Nebulas() {
  const sprites = useMemo(
    () => [
      { color: "rgba(167,139,250,0.20)", pos: [-24, 8, -30] as const, scale: 42 },
      { color: "rgba(34,211,238,0.15)", pos: [26, -6, -34] as const, scale: 48 },
      { color: "rgba(251,113,133,0.10)", pos: [4, 16, -40] as const, scale: 38 },
    ],
    [],
  );
  return (
    <>
      {sprites.map((s, i) => (
        <sprite key={i} position={s.pos as unknown as [number, number, number]} scale={[s.scale, s.scale, 1]}>
          <spriteMaterial map={nebulaTexture(s.color)} transparent depthWrite={false} blending={THREE.AdditiveBlending} />
        </sprite>
      ))}
    </>
  );
}

// --- the core ---------------------------------------------------------------

function Core({ intensity }: { intensity: number }) {
  const g = useRef<THREE.Group>(null);
  const inner = useRef<THREE.MeshStandardMaterial>(null);
  useFrame(({ clock }, dt) => {
    const t = clock.getElapsedTime();
    if (g.current) {
      g.current.rotation.y += dt * (0.1 + intensity * 0.5);
      const s = 1 + Math.sin(t * 1.2) * 0.04 + intensity * 0.08;
      g.current.scale.set(s, s, s);
    }
    if (inner.current) inner.current.emissiveIntensity = 0.8 + intensity * 1.6 + Math.sin(t * 2.4) * 0.25;
  });
  return (
    <group ref={g}>
      <mesh>
        <icosahedronGeometry args={[2.4, 1]} />
        <meshBasicMaterial color="#22d3ee" wireframe transparent opacity={0.22} />
      </mesh>
      <mesh rotation={[0.6, 0.3, 0]}>
        <icosahedronGeometry args={[1.8, 2]} />
        <meshBasicMaterial color="#a78bfa" wireframe transparent opacity={0.14} />
      </mesh>
      <mesh>
        <sphereGeometry args={[0.85, 32, 32]} />
        <meshStandardMaterial ref={inner} color="#0d1322" emissive="#22d3ee" roughness={0.25} metalness={0.7} />
      </mesh>
    </group>
  );
}

// --- division galaxies -------------------------------------------------------

function Galaxy({
  gx,
  position,
  dim,
  active,
  onSelect,
}: {
  gx: UniGalaxy;
  position: [number, number, number];
  dim: boolean;
  active: boolean;
  onSelect: () => void;
}) {
  const group = useRef<THREE.Group>(null);
  const [hover, setHover] = useState(false);
  const phase = useMemo(() => Math.random() * Math.PI * 2, []);

  const points = useMemo(() => {
    const n = 70;
    const arr = new Float32Array(n * 3);
    for (let i = 0; i < n; i++) {
      // flat swirl — a mini spiral galaxy
      const r = 0.25 + Math.pow(Math.random(), 0.6) * 1.15;
      const a = Math.random() * Math.PI * 2 + r * 2.2;
      arr[i * 3] = Math.cos(a) * r;
      arr[i * 3 + 1] = (Math.random() - 0.5) * 0.22;
      arr[i * 3 + 2] = Math.sin(a) * r;
    }
    return arr;
  }, []);

  useFrame(({ clock }, dt) => {
    const t = clock.getElapsedTime();
    if (group.current) {
      group.current.rotation.y += dt * (hover || active ? 1.1 : 0.35);
      group.current.position.y = position[1] + Math.sin(t * 0.7 + phase) * 0.3;
      const target = hover || active ? 1.35 : 1;
      group.current.scale.lerp(new THREE.Vector3(target, target, target), 0.07);
    }
  });

  const ratio = gx.total ? gx.active / gx.total : 0;
  return (
    <group position={position}>
      <group
        ref={group}
        onClick={(e) => {
          e.stopPropagation();
          onSelect();
        }}
        onPointerOver={(e) => {
          e.stopPropagation();
          setHover(true);
          blip();
          document.body.style.cursor = "pointer";
        }}
        onPointerOut={() => {
          setHover(false);
          document.body.style.cursor = "auto";
        }}
      >
        <points>
          <bufferGeometry>
            <bufferAttribute attach="attributes-position" count={points.length / 3} array={points} itemSize={3} />
          </bufferGeometry>
          <pointsMaterial
            size={0.09}
            color={gx.color}
            transparent
            opacity={dim ? 0.15 : 0.5 + ratio * 0.5}
            sizeAttenuation
            depthWrite={false}
            blending={THREE.AdditiveBlending}
          />
        </points>
        <mesh>
          <sphereGeometry args={[0.16, 16, 16]} />
          <meshStandardMaterial color={gx.color} emissive={gx.color} emissiveIntensity={dim ? 0.25 : 1.2} transparent opacity={dim ? 0.3 : 1} />
        </mesh>
      </group>
      {!dim && (
        <Html center distanceFactor={20} position={[0, 1.7, 0]} style={{ pointerEvents: "none" }}>
          <div
            style={{
              fontFamily: "ui-monospace, monospace",
              fontSize: 11,
              letterSpacing: 1.5,
              textTransform: "uppercase",
              color: gx.color,
              whiteSpace: "nowrap",
              textShadow: "0 0 14px rgba(0,0,0,0.95)",
              textAlign: "center",
              opacity: 0.9,
            }}
          >
            {gx.label}
            <div style={{ fontSize: 9, color: "#64748b" }}>{gx.active}/{gx.total} active</div>
          </div>
        </Html>
      )}
    </group>
  );
}

// --- floating metric nodes ---------------------------------------------------

function MetricNode({
  m,
  position,
  dim,
  active,
  onSelect,
}: {
  m: UniMetric;
  position: [number, number, number];
  dim: boolean;
  active: boolean;
  onSelect: () => void;
}) {
  const ref = useRef<THREE.Group>(null);
  const [hover, setHover] = useState(false);
  const phase = useMemo(() => Math.random() * Math.PI * 2, []);

  useFrame(({ clock }, dt) => {
    const t = clock.getElapsedTime();
    if (ref.current) {
      ref.current.position.y = position[1] + Math.sin(t * 0.9 + phase) * 0.25;
      ref.current.rotation.y += dt * 0.8;
      const target = hover || active ? 1.5 : 1;
      ref.current.scale.lerp(new THREE.Vector3(target, target, target), 0.08);
    }
  });

  return (
    <group position={position}>
      <group
        ref={ref}
        onClick={(e) => {
          e.stopPropagation();
          onSelect();
        }}
        onPointerOver={(e) => {
          e.stopPropagation();
          setHover(true);
          blip();
          document.body.style.cursor = "pointer";
        }}
        onPointerOut={() => {
          setHover(false);
          document.body.style.cursor = "auto";
        }}
      >
        <mesh>
          <octahedronGeometry args={[0.28, 0]} />
          <meshStandardMaterial
            color={m.color}
            emissive={m.color}
            emissiveIntensity={hover || active ? 1.8 : 0.9}
            transparent
            opacity={dim ? 0.25 : 0.95}
          />
        </mesh>
      </group>
      {!dim && (
        <Html center distanceFactor={16} position={[0, -0.85, 0]} style={{ pointerEvents: "none" }}>
          <div
            style={{
              fontFamily: "ui-monospace, monospace",
              textAlign: "center",
              whiteSpace: "nowrap",
              textShadow: "0 0 12px rgba(0,0,0,0.95)",
            }}
          >
            <div style={{ fontSize: 13, fontWeight: 600, color: m.color }}>{m.value}</div>
            <div style={{ fontSize: 8.5, letterSpacing: 1.5, textTransform: "uppercase", color: "#64748b" }}>{m.label}</div>
          </div>
        </Html>
      )}
    </group>
  );
}

// --- activity comets ----------------------------------------------------------

interface Comet {
  from: THREE.Vector3;
  to: THREE.Vector3;
  mid: THREE.Vector3;
  t: number;
  color: string;
}

function Comets({ pulse, galaxies }: { pulse: number; galaxies: UniGalaxy[] }) {
  const list = useRef<Comet[]>([]);
  const mesh = useRef<THREE.InstancedMesh>(null);
  const MAX = 14;

  useEffect(() => {
    // Real activity arrived → launch 1-2 light packets from the core outward.
    const n = Math.min(2, MAX - list.current.length);
    for (let i = 0; i < n; i++) {
      const gi = Math.floor(Math.random() * Math.max(1, galaxies.length));
      const to = new THREE.Vector3(...galaxyPos(gi, galaxies.length));
      list.current.push({
        from: new THREE.Vector3(0, 0, 0),
        to,
        mid: to.clone().multiplyScalar(0.5).add(new THREE.Vector3(0, 2.5, 0)),
        t: 0,
        color: galaxies[gi]?.color ?? "#22d3ee",
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pulse]);

  const dummy = useMemo(() => new THREE.Object3D(), []);

  useFrame((_, dt) => {
    const m = mesh.current;
    if (!m) return;
    list.current = list.current.filter((c) => c.t < 1);
    list.current.forEach((c) => (c.t += dt * 0.8));
    for (let i = 0; i < MAX; i++) {
      const c = list.current[i];
      if (c) {
        const t = Math.min(1, c.t);
        const a = c.from.clone().lerp(c.mid, t);
        const b = c.mid.clone().lerp(c.to, t);
        const p = a.lerp(b, t);
        dummy.position.copy(p);
        const s = 1 - Math.abs(t - 0.5) * 0.9;
        dummy.scale.setScalar(Math.max(0.001, s * 0.16));
      } else {
        dummy.scale.setScalar(0.0001);
      }
      dummy.updateMatrix();
      m.setMatrixAt(i, dummy.matrix);
    }
    m.instanceMatrix.needsUpdate = true;
  });

  return (
    <instancedMesh ref={mesh} args={[undefined, undefined, MAX]}>
      <sphereGeometry args={[1, 8, 8]} />
      <meshBasicMaterial color="#e0faff" transparent opacity={0.9} blending={THREE.AdditiveBlending} depthWrite={false} />
    </instancedMesh>
  );
}

// --- cinematic camera ----------------------------------------------------------

function Rig({ selected, galaxies }: { selected: UniSelection; galaxies: UniGalaxy[] }) {
  const { camera } = useThree();
  const angle = useRef(0.6);
  const look = useRef(new THREE.Vector3(0, 0, 0));

  useFrame(({ clock }, dt) => {
    const t = clock.getElapsedTime();
    let targetPos: THREE.Vector3;
    let targetLook = new THREE.Vector3(0, 0.4, 0);

    if (selected?.type === "galaxy") {
      const i = galaxies.findIndex((g) => g.key === selected.key);
      const p = new THREE.Vector3(...galaxyPos(Math.max(0, i), galaxies.length));
      targetPos = p.clone().multiplyScalar(1.35).add(new THREE.Vector3(0, 2.2, 0));
      targetLook = p;
    } else if (selected?.type === "metric") {
      // gentle push-in toward the core when inspecting a metric
      angle.current += dt * 0.02;
      const r = 11.5;
      targetPos = new THREE.Vector3(Math.sin(angle.current) * r, 4.5, Math.cos(angle.current) * r);
    } else {
      // idle: the camera never stops — slow orbit + breathing radius + bob
      angle.current += dt * 0.045;
      const r = 16.5 + Math.sin(t * 0.25) * 1.1;
      targetPos = new THREE.Vector3(
        Math.sin(angle.current) * r,
        5.4 + Math.sin(t * 0.18) * 1.0,
        Math.cos(angle.current) * r,
      );
    }

    camera.position.lerp(targetPos, 0.025);
    look.current.lerp(targetLook, 0.04);
    camera.lookAt(look.current);
  });
  return null;
}

// --- scene -----------------------------------------------------------------------

export default function Universe3D({ metrics, galaxies, intensity, pulse, selected, onSelect }: UniverseProps) {
  const mobile = useMemo(() => isCoarsePointer(), []);
  return (
    <Canvas
      camera={{ position: [0, 6, 17], fov: 55 }}
      dpr={[1, mobile ? 1.2 : 1.5]}
      gl={{ antialias: !mobile }}
      onPointerMissed={() => onSelect(null)}
    >
      <color attach="background" args={["#020409"]} />
      <fog attach="fog" args={["#020409", 24, 55]} />
      <ambientLight intensity={0.45} />
      <pointLight position={[0, 8, 0]} intensity={1.4} color="#22d3ee" />
      <pointLight position={[-10, -4, 8]} intensity={0.6} color="#a78bfa" />

      <Stars radius={90} depth={60} count={mobile ? 1500 : 3500} factor={3.4} fade speed={0.9} />
      <Nebulas />
      <Rig selected={selected} galaxies={galaxies} />
      <Core intensity={intensity} />
      <Comets pulse={pulse} galaxies={galaxies} />

      {galaxies.map((gx, i) => {
        const pos = galaxyPos(i, galaxies.length);
        const dimmed = !!selected && !(selected.type === "galaxy" && selected.key === gx.key);
        return (
          <group key={gx.key}>
            <QuadraticBezierLine
              start={[0, 0, 0]}
              mid={[pos[0] * 0.5, 2.2 + Math.sin(i) * 0.8, pos[2] * 0.5]}
              end={pos}
              color={gx.color}
              lineWidth={0.7}
              transparent
              opacity={dimmed ? 0.05 : 0.14 + (gx.total ? gx.active / gx.total : 0) * 0.3 + intensity * 0.15}
            />
            <Galaxy
              gx={gx}
              position={pos}
              dim={dimmed}
              active={selected?.type === "galaxy" && selected.key === gx.key}
              onSelect={() => onSelect(selected?.type === "galaxy" && selected.key === gx.key ? null : { type: "galaxy", key: gx.key })}
            />
          </group>
        );
      })}

      {metrics.map((m, i) => (
        <MetricNode
          key={m.key}
          m={m}
          position={metricPos(i, metrics.length)}
          dim={!!selected && !(selected.type === "metric" && selected.key === m.key)}
          active={selected?.type === "metric" && selected.key === m.key}
          onSelect={() => onSelect(selected?.type === "metric" && selected.key === m.key ? null : { type: "metric", key: m.key })}
        />
      ))}

      {!mobile && (
        <EffectComposer>
          <Bloom intensity={0.9} luminanceThreshold={0.18} luminanceSmoothing={0.9} mipmapBlur />
        </EffectComposer>
      )}
    </Canvas>
  );
}
