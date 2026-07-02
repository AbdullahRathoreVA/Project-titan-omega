"use client";

// Cinematic boot overlay: black screen → startup sound + AI voice → particle
// text assembly → camera fly-through → dashboard reveal. Plays once per
// browser session; always skippable. The dashboard loads underneath so data is
// ready the moment the overlay lifts.

import { useEffect, useRef, useState } from "react";
import dynamic from "next/dynamic";
import { motion, AnimatePresence } from "framer-motion";
import { bootSound, speak } from "@/lib/sound";

const Scene = dynamic(() => import("./BootScene3D"), { ssr: false, loading: () => null });

const BOOT_MS = 7200;

export function BootSequence({ onDone }: { onDone: () => void }) {
  const [visible, setVisible] = useState(true);
  const done = useRef(false);

  const finish = () => {
    if (done.current) return;
    done.current = true;
    try {
      window.speechSynthesis?.cancel();
    } catch {
      /* silent */
    }
    setVisible(false);
    setTimeout(onDone, 650); // let the exit fade play
  };

  useEffect(() => {
    bootSound();
    const voice = setTimeout(
      () => speak("Welcome back Abdullah Boss. Titan Founder A I is online. All systems operational."),
      900,
    );
    const t = setTimeout(finish, BOOT_MS);
    return () => {
      clearTimeout(t);
      clearTimeout(voice);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <AnimatePresence>
      {visible && (
        <motion.div
          initial={{ opacity: 1 }}
          exit={{ opacity: 0, scale: 1.06 }}
          transition={{ duration: 0.65, ease: "easeInOut" }}
          className="fixed inset-0 z-[300] bg-[#020409]"
        >
          <div className="absolute inset-0">
            <Scene />
          </div>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 4.6, duration: 1.2 }}
            className="pointer-events-none absolute inset-x-0 bottom-16 text-center font-mono text-[11px] tracking-[0.35em] text-hud-cyan/70"
          >
            TITAN FOUNDER AI · ALL SYSTEMS OPERATIONAL
          </motion.div>
          <button
            onClick={finish}
            className="absolute bottom-5 right-6 rounded-lg border border-edge bg-panel/60 px-3 py-1.5 font-mono text-[10px] tracking-widest text-slate-500 transition-colors hover:border-hud-cyan/40 hover:text-hud-cyan"
          >
            SKIP ▸
          </button>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
