"use client";

import { useEffect } from "react";

/**
 * Registers the service worker that makes Titan installable.
 *
 * Kept as its own client component so app/layout.tsx stays a server component —
 * marking the whole layout "use client" would opt every page out of static
 * generation, and the Space serves a static export.
 *
 * Registration is deliberately quiet: a browser without service worker support,
 * or a page served over plain HTTP during local development, must not throw
 * into the console on every load.
 */
export function RegisterSW() {
  useEffect(() => {
    if (typeof window === "undefined") return;
    // Tell the boot watchdog in app/layout.tsx the app is running, and let a
    // later failed load in this session recover again.
    (window as unknown as { __titanBooted?: boolean }).__titanBooted = true;
    try {
      sessionStorage.removeItem("titan-boot-recoveries");
    } catch {
      /* storage can be blocked; the watchdog copes without it */
    }
    if (!("serviceWorker" in navigator)) return;
    // Service workers require a secure context. localhost counts as secure, so
    // this still works in development.
    if (!window.isSecureContext) return;

    const register = () => {
      navigator.serviceWorker.register("/sw.js").catch(() => {
        /* Installability is a bonus, never a hard requirement. */
      });
    };

    // Wait for load so registration doesn't compete with the first paint of the
    // 3D scene, already the heaviest thing on the page.
    if (document.readyState === "complete") register();
    else window.addEventListener("load", register, { once: true });
  }, []);

  return null;
}
