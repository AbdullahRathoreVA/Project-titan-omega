"use client";

// Cinematic boot overlay: black screen → startup sound + AI voice → particle
// text assembly → camera fly-through → dashboard reveal. Plays on every open;
// always skippable. On touch devices we gate behind a TAP — phones refuse to
// play audio/voice until the user interacts, so the tap unlocks the sound.

import { useEffect, useRef, useState } from "react";
import dynamic from "next/dynamic";
import { motion, AnimatePresence } from "framer-motion";
import { bootSound, speak } from "@/lib/sound";
import { isCoarsePointer } from "@/lib/device";

const Scene = dynamic(() => import("./BootScene3D"), { ssr: false, loading: () => null });

const BOOT_MS = 7200;

export function BootSequence({ onDone }: { onDone: () => void }) {
  const [visible, setVisible] = useState(true);
  // null = deciding, false = waiting for tap (touch devices), true = running
  const [started, setStarted] = useState<boolean | null>(null);
  const done = useRef(false);

  const finish = (skipped = false) => {
    if (done.current) return;
    done.current = true;
    // Only cut the voice when the founder SKIPS — on a natural finish the
    // welcome line keeps speaking and the live briefing queues right after it.
    if (skipped) {
      try {
        window.speechSynthesis?.cancel();
      } catch {
        /* silent */
      }
    }
    setVisible(false);
    setTimeout(onDone, 650); // let the exit fade play
  };

  useEffect(() => {
    setStarted(isCoarsePointer() ? false : true);
  }, []);

  useEffect(() => {
    if (started !== true) return;
    bootSound();
    const voice = setTimeout(
      () => speak("Welcome back Abdullah Boss. Titan Founder A I is online. All systems operational."),
      900,
    );
    const t = setTimeout(() => finish(false), BOOT_MS);
    return () => {
      clearTimeout(t);
      clearTimeout(voice);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [started]);

  return (
    <AnimatePresence>
      {visible && (
        <motion.div
          initial={{ opacity: 1 }}
          exit={{ opacity: 0, scale: 1.06 }}
          transition={{ duration: 0.65, ease: "easeInOut" }}
          className="fixed inset-0 z-[300] bg-[#020409]"
        >
          {started === true && (
            <div className="absolute inset-0">
              <Scene />
            </div>
          )}

          {started === false && (
            <button
              onClick={() => setStarted(true)}
              className="absolute inset-0 flex flex-col items-center justify-center gap-4"
            >
              <span className="h-16 w-16 animate-pulseGlow rounded-full border border-hud-cyan/60 shadow-glow" />
              <span className="animate-pulseGlow font-mono text-xs tracking-[0.4em] text-hud-cyan">
                TAP TO INITIALIZE TITAN
              </span>
              <span className="font-mono text-[9px] tracking-widest text-slate-600">
                sound + voice unlock on tap
              </span>
            </button>
          )}

          {started === true && (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ delay: 4.6, duration: 1.2 }}
              className="pointer-events-none absolute inset-x-0 bottom-16 text-center font-mono text-[11px] tracking-[0.35em] text-hud-cyan/70"
            >
              TITAN FOUNDER AI · ALL SYSTEMS OPERATIONAL
            </motion.div>
          )}

          <button
            onClick={() => finish(true)}
            className="absolute bottom-5 right-6 rounded-lg border border-edge bg-panel/60 px-3 py-1.5 font-mono text-[10px] tracking-widest text-slate-500 transition-colors hover:border-hud-cyan/40 hover:text-hud-cyan"
          >
            SKIP ▸
          </button>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
