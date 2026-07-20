"use client";

import { useCallback, useEffect, useState } from "react";
import { LogOut } from "lucide-react";
import { api, getToken, setToken, verifyToken } from "@/lib/api";
import { Login } from "./Login";
import { CommandCenter } from "./CommandCenter";

// Decides whether to show the login screen or the dashboard. When the core does
// not require auth (local dev / auth disabled), it goes straight to the
// dashboard. When auth IS required, we VERIFY the stored token actually works
// before trusting it — otherwise a stale token (e.g. after changing the
// username/password) would silently trap the dashboard in 401/demo mode.
//
// The SAME deployment also serves a public read-only demo: "View the live demo"
// on the login screen starts a guest session (GET-only, private data replaced
// with sample content), so one Space covers both the founder and the public.

const GUEST_FLAG = "titan_guest_session";

function markGuest(on: boolean) {
  try {
    (window as unknown as { __TITAN_GUEST?: boolean }).__TITAN_GUEST = on;
    if (on) sessionStorage.setItem(GUEST_FLAG, "1");
    else sessionStorage.removeItem(GUEST_FLAG);
  } catch {
    /* private mode — flag still set on window */
  }
}

export function AuthGate() {
  const [state, setState] = useState<"loading" | "login" | "ready">("loading");
  const [demo, setDemo] = useState(true);
  const [guestAvailable, setGuestAvailable] = useState(true);
  const [guest, setGuest] = useState(false);

  const probe = useCallback(async () => {
    const status = await api.authStatus();
    setDemo(status.demo);
    setGuestAvailable(status.guest_available !== false);

    // A whole-Space guest deploy (legacy TITAN_GUEST_MODE) needs no login.
    if (status.guest) {
      markGuest(true);
      setGuest(true);
      setState("ready");
      return;
    }

    if (!status.required) {
      setState("ready");
      return;
    }

    const token = getToken();
    if (!token) {
      setState("login");
      return;
    }

    // Verify the stored token really works; if it's stale, force a fresh login.
    const ok = await verifyToken();
    if (ok) {
      // Restore the guest badge if this tab's session was a demo session.
      let wasGuest = false;
      try {
        wasGuest = sessionStorage.getItem(GUEST_FLAG) === "1";
      } catch {
        /* ignore */
      }
      markGuest(wasGuest);
      setGuest(wasGuest);
      setState("ready");
    } else {
      setToken(null);
      markGuest(false);
      setState("login");
    }
  }, []);

  useEffect(() => {
    void probe();
  }, [probe]);

  if (state === "loading") {
    return (
      <main className="flex min-h-screen items-center justify-center">
        <span className="animate-pulseGlow font-mono text-sm text-hud-cyan">
          Booting Titan Omega…
        </span>
      </main>
    );
  }
  if (state === "login") {
    return (
      <Login
        demo={demo}
        guestAvailable={guestAvailable}
        onSuccess={() => {
          markGuest(false);
          setGuest(false);
          setState("ready");
        }}
        onGuest={() => {
          markGuest(true);
          setGuest(true);
          setState("ready");
        }}
      />
    );
  }
  const signOut = () => {
    setToken(null);
    markGuest(false);
    setState("login");
  };

  return (
    <>
      <div className="fixed right-3 top-3 z-[999] flex items-center gap-2">
        {guest && (
          <span className="rounded border border-hud-violet/40 bg-black/70 px-3 py-1 font-mono text-[11px] tracking-wide text-hud-violet">
            DEMO · read-only · sample data
          </span>
        )}
        <button
          onClick={signOut}
          title={guest ? "Exit the demo and sign in" : "Sign out"}
          className="flex items-center gap-1.5 rounded border border-edge bg-black/70 px-3 py-1 font-mono text-[11px] tracking-wide text-slate-400 transition-colors hover:border-hud-cyan/40 hover:text-hud-cyan"
        >
          <LogOut className="h-3 w-3" />
          {guest ? "Exit demo" : "Sign out"}
        </button>
      </div>
      <CommandCenter />
    </>
  );
}
