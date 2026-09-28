"use client";

// Boot overlay: black screen -> startup sound + AI voice -> particle text
// assembly -> camera fly-through -> dashboard reveal. Plays on every open;
// always skippable.
//
// Browsers (desktop included, not just phones) block sound and speech until
// the user interacts, so the whole boot waits for a single tap/click and
// fires the sound and voice inside that gesture. That's what makes the voice
// work reliably on Android, iPhone, Mac and desktop.

import { useEffect, useRef, useState } from "react";
import dynamic from "next/dynamic";
import { motion, AnimatePresence } from "framer-motion";
import { bootSound, speak, unlockAudio } from "@/lib/sound";
import { displayName, isCustomer, isDemo } from "@/lib/session";

const Scene = dynamic(() => import("./BootScene3D"), { ssr: false, loading: () => null });

const BOOT_MS = 7200;

function isGuest(): boolean {
  return (
    typeof window !== "undefined" &&
    (window as unknown as { __TITAN_GUEST?: boolean }).__TITAN_GUEST === true
  );
}

export function BootSequence({ onDone }: { onDone: () => void }) {
  const [visible, setVisible] = useState(true);
  // Wait for a tap/click on every device - the only reliable way to unlock
  // audio and voice. false = waiting for the gesture, true = running.
  const [started, setStarted] = useState(false);
  const done = useRef(false);

  const finish = (skipped = false) => {
    if (done.current) return;
    done.current = true;
    // Only cut the voice when the user skips. On a natural finish the welcome
    // line keeps speaking and the live briefing queues right after it.
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

  const begin = () => {
    if (started) return;
    // These must run synchronously inside the click/tap handler, or
    // iOS/Android/Safari silently refuse the audio and the voice.
    unlockAudio();
    bootSound();
    speak(
      isGuest() || isDemo()
        ? "Welcome to Titan Omega. Autonomous A I business system, online. All systems operational."
        : isCustomer()
          ? `Welcome, ${displayName()}. Your Titan workspace is online. All systems operational.`
          : "Welcome back Abdullah. Titan Founder A I is online. All systems operational.",
    );
    setStarted(true);
  };

  useEffect(() => {
    if (!started) return;
    const t = setTimeout(() => finish(false), BOOT_MS);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [started]);

  return (
    <AnimatePresence>
      {visible && (
        <motion.div
          initial={{ opacity: 1 }}
          exit={{ opacity: 0, scale: 1.06 }}
          transition={{ duration: 0.65, ease: "easeInOut" }}
          className="fixed inset-0 z-[900] bg-[#020409]"
          // Force this overlay onto its own compositor layer so a fixed WebGL
          // backdrop can't bleed through it on mobile (iOS/Android quirk).
          style={{ transform: "translateZ(0)" }}
        >
          {started && (
            <div className="absolute inset-0">
              <Scene />
            </div>
          )}

          {!started && (
            <button
              onClick={begin}
              className="absolute inset-0 flex flex-col items-center justify-center gap-4"
            >
              <span className="h-16 w-16 animate-pulseGlow rounded-full border border-hud-cyan/60 shadow-glow" />
              <span className="animate-pulseGlow font-mono text-xs tracking-[0.4em] text-hud-cyan">
                TAP TO INITIALIZE TITAN
              </span>
              <span className="font-mono text-[9px] tracking-widest text-slate-600">
                turns on sound + voice · works on every device
              </span>
            </button>
          )}

          {started && (
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
            {started ? "SKIP ▸" : "ENTER SILENTLY ▸"}
          </button>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
