"use client";

// The AI City: each division is a floating neon district in a ring around the
// Titan core, tied together by energy strings. Clicking a district flies the
// camera to it (no page change).

import { useMemo, useRef, useState } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import { Html, QuadraticBezierLine, Stars } from "@react-three/drei";
import { EffectComposer, Bloom } from "@react-three/postprocessing";
import * as THREE from "three";
import type { DivisionView } from "@/lib/types";
import { blip } from "@/lib/sound";
import { isCoarsePointer } from "@/lib/device";

const RING_RADIUS = 6.2;
const DISTRICT_COLORS = ["#22d3ee", "#a78bfa", "#34d399", "#fbbf24", "#fb7185", "#3b82f6"];

export interface CityProps {
  divisions: DivisionView[];
  selected: string | null;
  onSelect: (division: string | null) => void;
  intensity: number;
}

function districtPosition(index: number, total: number): [number, number, number] {
  const angle = (index / Math.max(1, total)) * Math.PI * 2;
  return [Math.cos(angle) * RING_RADIUS, 0, Math.sin(angle) * RING_RADIUS];
}

function District({
  division,
  position,
  color,
  active,
  dim,
  onSelect,
}: {
  division: DivisionView;
  position: [number, number, number];
  color: string;
  active: boolean;
  dim: boolean;
  onSelect: () => void;
}) {
  const group = useRef<THREE.Group>(null);
  const [hover, setHover] = useState(false);
  const phase = useMemo(() => Math.random() * Math.PI * 2, []);

  useFrame(({ clock }) => {
    const t = clock.getElapsedTime();
    if (group.current) {
      group.current.position.y = position[1] + Math.sin(t * 0.9 + phase) * 0.22;
      group.current.rotation.y = t * 0.35 + phase;
      const target = hover || active ? 1.28 : 1;
      group.current.scale.lerp(new THREE.Vector3(target, target, target), 0.08);
    }
  });

  const emissive = hover || active ? 1.6 : 0.7;
  const opacity = dim ? 0.25 : 1;

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
        <mesh>
          <octahedronGeometry args={[0.62, 0]} />
          <meshStandardMaterial
            color={color}
            emissive={color}
            emissiveIntensity={emissive}
            transparent
            opacity={opacity}
            roughness={0.25}
            metalness={0.7}
          />
        </mesh>
        <mesh rotation={[Math.PI / 2, 0, 0]} position={[0, -0.85, 0]}>
          <torusGeometry args={[0.55, 0.02, 8, 48]} />
          <meshBasicMaterial color={color} transparent opacity={0.5 * opacity} />
        </mesh>
      </group>
      {!dim && (
        <Html center distanceFactor={13} position={[0, 1.35, 0]} style={{ pointerEvents: "none" }}>
          <div
            style={{
              fontFamily: "ui-monospace, monospace",
              fontSize: 11,
              letterSpacing: 1,
              color: hover || active ? color : "#8fa3c0",
              textTransform: "uppercase",
              whiteSpace: "nowrap",
              textShadow: "0 0 12px rgba(0,0,0,0.9)",
              textAlign: "center",
            }}
          >
            {division.division}
            <div style={{ fontSize: 9, color: "#5a6b85" }}>
              {division.active_agents}/{division.agent_count} active
            </div>
          </div>
        </Html>
      )}
    </group>
  );
}

function Core({ intensity }: { intensity: number }) {
  const ref = useRef<THREE.Group>(null);
  useFrame((_, dt) => {
    if (ref.current) ref.current.rotation.y += dt * (0.15 + intensity * 0.6);
  });
  return (
    <group ref={ref}>
      <mesh>
        <icosahedronGeometry args={[1.05, 1]} />
        <meshBasicMaterial color="#22d3ee" wireframe transparent opacity={0.3} />
      </mesh>
      <mesh>
        <sphereGeometry args={[0.45, 32, 32]} />
        <meshStandardMaterial color="#0d1322" emissive="#22d3ee" emissiveIntensity={0.9 + intensity} roughness={0.3} metalness={0.6} />
      </mesh>
    </group>
  );
}

function CameraRig({ selectedPos }: { selectedPos: [number, number, number] | null }) {
  // Home sits higher and further back so the whole city, ground ring included,
  // fits the frame on every screen.
  const home = useMemo(() => new THREE.Vector3(0, 6.8, 13.6), []);
  const look = useRef(new THREE.Vector3(0, 0.4, 0));

  useFrame(({ camera }) => {
    const target = selectedPos
      ? new THREE.Vector3(selectedPos[0] * 1.35, 2.2, selectedPos[2] * 1.35)
      : home;
    camera.position.lerp(target, 0.045);
    const lookTarget = selectedPos
      ? new THREE.Vector3(selectedPos[0], 0.4, selectedPos[2])
      : new THREE.Vector3(0, 0.4, 0);
    look.current.lerp(lookTarget, 0.06);
    camera.lookAt(look.current);
  });
  return null;
}

export default function AICity3D({ divisions, selected, onSelect, intensity }: CityProps) {
  const mobile = useMemo(() => isCoarsePointer(), []);
  const positions = useMemo(
    () => divisions.map((_, i) => districtPosition(i, divisions.length)),
    [divisions],
  );
  const selIndex = divisions.findIndex((d) => d.division === selected);
  const selectedPos = selIndex >= 0 ? positions[selIndex] : null;

  return (
    <Canvas camera={{ position: [0, 6.8, 13.6], fov: 52 }} dpr={[1, mobile ? 1.2 : 1.5]} gl={{ antialias: !mobile }}>
      <ambientLight intensity={0.45} />
      <pointLight position={[0, 6, 0]} intensity={1.2} color="#22d3ee" />
      <pointLight position={[-6, -3, 6]} intensity={0.7} color="#a78bfa" />
      <Stars radius={65} depth={40} count={mobile ? 900 : 1800} factor={3} fade speed={0.8} />
      <gridHelper args={[36, 36, "#1b2a4a", "#0c1220"]} position={[0, -1.85, 0]} />
      <CameraRig selectedPos={selectedPos} />
      <Core intensity={intensity} />
      {divisions.map((d, i) => (
        <group key={d.division}>
          <QuadraticBezierLine
            start={[0, 0, 0]}
            mid={[positions[i][0] * 0.5, 1.1, positions[i][2] * 0.5]}
            end={positions[i]}
            color={DISTRICT_COLORS[i % DISTRICT_COLORS.length]}
            lineWidth={0.8}
            transparent
            opacity={selected && d.division !== selected ? 0.08 : 0.32 + intensity * 0.3}
          />
          <District
            division={d}
            position={positions[i]}
            color={DISTRICT_COLORS[i % DISTRICT_COLORS.length]}
            active={d.division === selected}
            dim={!!selected && d.division !== selected}
            onSelect={() => onSelect(d.division === selected ? null : d.division)}
          />
        </group>
      ))}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -1.35, 0]}>
        <ringGeometry args={[RING_RADIUS - 0.35, RING_RADIUS + 0.35, 96]} />
        <meshBasicMaterial color="#16203a" transparent opacity={0.55} side={THREE.DoubleSide} />
      </mesh>
      {!mobile && (
        <EffectComposer>
          <Bloom intensity={0.85} luminanceThreshold={0.18} luminanceSmoothing={0.9} mipmapBlur />
        </EffectComposer>
      )}
    </Canvas>
  );
}
