"use client";

// AI "thinking" visualization — replaces generic spinners with a staged
// reasoning trace so the user always sees what the AI is doing.

import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Brain } from "lucide-react";

const STAGES = [
  "Planning approach",
  "Retrieving context",
  "Reasoning over options",
  "Executing",
  "Verifying result",
];

export function ThinkingTrace({ label = "Titan is thinking" }: { label?: string }) {
  const [i, setI] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setI((p) => (p + 1) % STAGES.length), 950);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="flex items-center gap-2 rounded-lg border border-hud-cyan/30 bg-hud-cyan/5 px-3 py-1.5">
      <Brain className="h-3.5 w-3.5 animate-pulse text-hud-cyan" strokeWidth={1.8} />
      <span className="font-mono text-[11px] text-slate-500">{label}</span>
      <span className="relative h-[15px] min-w-[130px] overflow-hidden text-xs">
        <AnimatePresence mode="wait">
          <motion.span
            key={i}
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -6 }}
            transition={{ duration: 0.25 }}
            className="absolute inset-0 text-hud-cyan"
          >
            {STAGES[i]}…
          </motion.span>
        </AnimatePresence>
      </span>
      <span className="ml-auto flex gap-0.5">
        {[0, 1, 2].map((d) => (
          <span
            key={d}
            className="h-1 w-1 animate-pulse rounded-full bg-hud-cyan"
            style={{ animationDelay: `${d * 0.2}s` }}
          />
        ))}
      </span>
    </div>
  );
}
