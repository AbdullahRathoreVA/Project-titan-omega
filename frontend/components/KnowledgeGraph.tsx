"use client";

// Knowledge Graph - an animated force-directed map: executive core <-> 12
// divisions <-> agents, with workflow hand-off lanes drawn as flowing links.
// Plain canvas: no extra dependencies, capped DPR, hover to inspect, click a
// division to focus it.

import { useEffect, useMemo, useRef, useState } from "react";
import { Network } from "lucide-react";
import type { AgentView, DivisionView } from "@/lib/types";

// Mirrors backend engines/workflows.py hand-off targets.
const HANDOFFS: [string, string][] = [
  ["intelligence", "growth"],
  ["growth", "marketing"],
  ["revenue", "partnerships"],
  ["product", "technology"],
  ["customer", "product"],
  ["partnerships", "finance"],
  ["innovation", "executive"],
  ["operations", "executive"],
];

const DIV_COLOR: Record<string, string> = {
  executive: "#22d3ee",
  marketing: "#f472b6",
  growth: "#34d399",
  intelligence: "#a78bfa",
  revenue: "#fbbf24",
  product: "#60a5fa",
  technology: "#38bdf8",
  finance: "#facc15",
  customer: "#fb7185",
  partnerships: "#4ade80",
  innovation: "#c084fc",
  operations: "#94a3b8",
};

type Node = {
  id: string;
  label: string;
  kind: "core" | "division" | "agent";
  color: string;
  x: number;
  y: number;
  vx: number;
  vy: number;
  r: number;
  meta?: string;
};

export function KnowledgeGraph({
  divisions,
  agents,
}: {
  divisions: DivisionView[];
  agents: AgentView[];
}) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [hover, setHover] = useState<string | null>(null);
  const [focusDiv, setFocusDiv] = useState<string | null>(null);
  const hoverRef = useRef<string | null>(null);
  const focusRef = useRef<string | null>(null);
  hoverRef.current = hover;
  focusRef.current = focusDiv;

  // Build nodes/links once per data change.
  const { nodes, links } = useMemo(() => {
    const ns: Node[] = [];
    const ls: [string, string, number][] = []; // [from, to, strength]
    ns.push({ id: "core", label: "TITAN Ω", kind: "core", color: "#22d3ee", x: 0, y: 0, vx: 0, vy: 0, r: 17 });

    const divIds = divisions.map((d) => String(d.division));
    divIds.forEach((dv, i) => {
      const ang = (i / Math.max(1, divIds.length)) * Math.PI * 2;
      const d = divisions[i];
      ns.push({
        id: `div:${dv}`,
        label: dv.toUpperCase(),
        kind: "division",
        color: DIV_COLOR[dv] ?? "#94a3b8",
        x: Math.cos(ang) * 170,
        y: Math.sin(ang) * 170,
        vx: 0,
        vy: 0,
        r: 10,
        meta: `${d.active_agents}/${d.agent_count} active`,
      });
      ls.push(["core", `div:${dv}`, 0.9]);
    });
    for (const [a, b] of HANDOFFS) {
      if (divIds.includes(a) && divIds.includes(b)) ls.push([`div:${a}`, `div:${b}`, 0.35]);
    }
    // Top agents per division (working first, by impact) keep it readable.
    const byDiv = new Map<string, AgentView[]>();
    for (const a of agents) {
      const k = String(a.division);
      byDiv.set(k, [...(byDiv.get(k) ?? []), a]);
    }
    for (const [dv, list] of byDiv) {
      const top = list
        .sort((x, y) => (y.status === "working" ? 1 : 0) - (x.status === "working" ? 1 : 0) || y.impact_score - x.impact_score)
        .slice(0, 3);
      const host = ns.find((n) => n.id === `div:${dv}`);
      if (!host) continue;
      top.forEach((a, j) => {
        ns.push({
          id: `ag:${a.id}`,
          label: a.name,
          kind: "agent",
          color: DIV_COLOR[dv] ?? "#94a3b8",
          x: host.x + Math.cos(j * 2.1) * 46,
          y: host.y + Math.sin(j * 2.1) * 46,
          vx: 0,
          vy: 0,
          r: a.is_head ? 6 : 4.5,
          meta: a.current_task ?? a.mission,
        });
        ls.push([`div:${dv}`, `ag:${a.id}`, 0.6]);
      });
    }
    return { nodes: ns, links: ls };
  }, [divisions, agents]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || nodes.length === 0) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const dpr = Math.min(1.5, window.devicePixelRatio || 1);
    let W = 0;
    let H = 0;
    const size = () => {
      const rect = canvas.getBoundingClientRect();
      W = rect.width;
      H = rect.height;
      canvas.width = W * dpr;
      canvas.height = H * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    size();
    window.addEventListener("resize", size);

    const byId = new Map(nodes.map((n) => [n.id, n]));
    let raf = 0;
    let t = 0;

    const step = () => {
      t += 0.016;
      // physics: springs on links, soft repulsion, center gravity
      for (const [a, b, k] of links) {
        const na = byId.get(a)!;
        const nb = byId.get(b)!;
        const dx = nb.x - na.x;
        const dy = nb.y - na.y;
        const dist = Math.max(20, Math.hypot(dx, dy));
        const rest = na.kind === "core" ? 175 : 52;
        const f = ((dist - rest) / dist) * 0.012 * k;
        na.vx += dx * f;
        na.vy += dy * f;
        nb.vx -= dx * f;
        nb.vy -= dy * f;
      }
      for (let i = 0; i < nodes.length; i++) {
        for (let j = i + 1; j < nodes.length; j++) {
          const a = nodes[i];
          const b = nodes[j];
          const dx = b.x - a.x;
          const dy = b.y - a.y;
          const d2 = dx * dx + dy * dy + 40;
          if (d2 < 9000) {
            const f = 46 / d2;
            a.vx -= dx * f;
            a.vy -= dy * f;
            b.vx += dx * f;
            b.vy += dy * f;
          }
        }
      }
      for (const n of nodes) {
        if (n.kind === "core") {
          n.x = 0;
          n.y = 0;
          continue;
        }
        n.vx -= n.x * 0.0008;
        n.vy -= n.y * 0.0008;
        n.vx *= 0.86;
        n.vy *= 0.86;
        n.x += n.vx;
        n.y += n.vy;
      }

      // draw
      ctx.clearRect(0, 0, W, H);
      const cx = W / 2;
      const cy = H / 2;
      const focus = focusRef.current;

      ctx.save();
      ctx.translate(cx, cy);
      for (const [a, b, k] of links) {
        const na = byId.get(a)!;
        const nb = byId.get(b)!;
        const isHand = na.kind === "division" && nb.kind === "division";
        const dim =
          focus && !(na.id === `div:${focus}` || nb.id === `div:${focus}` || na.kind === "core" || nb.kind === "core");
        ctx.strokeStyle = isHand ? "rgba(167,139,250,0.5)" : `rgba(56,189,248,${dim ? 0.06 : 0.16 * k + 0.08})`;
        ctx.lineWidth = isHand ? 1.2 : 0.7;
        ctx.beginPath();
        ctx.moveTo(na.x, na.y);
        ctx.lineTo(nb.x, nb.y);
        ctx.stroke();
        // flowing packet on hand-off lanes
        if (isHand && !dim) {
          const p = (t * 0.35 + (a.charCodeAt(4) % 10) / 10) % 1;
          const px = na.x + (nb.x - na.x) * p;
          const py = na.y + (nb.y - na.y) * p;
          ctx.fillStyle = "#a78bfa";
          ctx.beginPath();
          ctx.arc(px, py, 2, 0, 7);
          ctx.fill();
        }
      }
      for (const n of nodes) {
        const isHover = hoverRef.current === n.id;
        const dim = focus && n.kind !== "core" && !n.id.includes(focus) && !(n.kind === "agent" && n.color === DIV_COLOR[focus]);
        ctx.globalAlpha = dim ? 0.25 : 1;
        const pulse = n.kind === "core" ? 1 + Math.sin(t * 2) * 0.06 : 1;
        ctx.fillStyle = n.color;
        ctx.shadowColor = n.color;
        ctx.shadowBlur = isHover ? 18 : n.kind === "agent" ? 4 : 10;
        ctx.beginPath();
        ctx.arc(n.x, n.y, n.r * pulse * (isHover ? 1.25 : 1), 0, 7);
        ctx.fill();
        ctx.shadowBlur = 0;
        if (n.kind !== "agent" || isHover) {
          ctx.fillStyle = isHover ? "#e2e8f0" : "rgba(148,163,184,0.85)";
          ctx.font = `${n.kind === "core" ? "700 11px" : "600 8.5px"} ui-monospace, monospace`;
          ctx.textAlign = "center";
          ctx.fillText(n.label, n.x, n.y + n.r + 11);
          if (isHover && n.meta) {
            ctx.fillStyle = "rgba(148,163,184,0.7)";
            ctx.font = "8px ui-monospace, monospace";
            ctx.fillText(n.meta.slice(0, 46), n.x, n.y + n.r + 21);
          }
        }
        ctx.globalAlpha = 1;
      }
      ctx.restore();
      raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);

    const pick = (mx: number, my: number): Node | null => {
      const x = mx - W / 2;
      const y = my - H / 2;
      let best: Node | null = null;
      let bd = 18;
      for (const n of nodes) {
        const d = Math.hypot(n.x - x, n.y - y);
        if (d < bd + n.r) {
          bd = d;
          best = n;
        }
      }
      return best;
    };
    const onMove = (e: MouseEvent) => {
      const rect = canvas.getBoundingClientRect();
      const n = pick(e.clientX - rect.left, e.clientY - rect.top);
      setHover(n?.id ?? null);
      canvas.style.cursor = n ? "pointer" : "default";
    };
    const onClick = (e: MouseEvent) => {
      const rect = canvas.getBoundingClientRect();
      const n = pick(e.clientX - rect.left, e.clientY - rect.top);
      if (n?.kind === "division") {
        const dv = n.id.slice(4);
        setFocusDiv((f) => (f === dv ? null : dv));
      } else if (!n) {
        setFocusDiv(null);
      }
    };
    canvas.addEventListener("mousemove", onMove);
    canvas.addEventListener("click", onClick);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", size);
      canvas.removeEventListener("mousemove", onMove);
      canvas.removeEventListener("click", onClick);
    };
  }, [nodes, links]);

  return (
    <section className="panel relative h-[560px] overflow-hidden">
      <header className="panel-header">
        <div className="flex items-center gap-2">
          <Network className="h-4 w-4 text-hud-violet" strokeWidth={1.6} />
          <h2 className="text-sm font-medium text-slate-200">Knowledge Graph</h2>
        </div>
        <span className="hud-label">
          {focusDiv ? `focus: ${focusDiv} · click background to reset` : "hover to inspect · click a division to focus"}
        </span>
      </header>
      <canvas ref={canvasRef} className="h-[calc(100%-41px)] w-full" />
    </section>
  );
}
