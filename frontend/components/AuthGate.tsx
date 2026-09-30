"use client";

import { useCallback, useEffect, useState } from "react";
import { LogOut } from "lucide-react";
import { api, getToken, setToken, verifyCustomer, verifyToken } from "@/lib/api";
import { getCustomerToken, setCustomerToken } from "@/lib/session";
import { Login } from "./Login";
import { CommandCenter } from "./CommandCenter";

// Decides whether to show the login screen or the dashboard. When the backend
// doesn't require auth (local dev), it goes straight to the dashboard. When
// it does, the stored token is verified before it's trusted, so a stale token
// (e.g. after changing the username/password) can't trap the dashboard in
// 401/demo mode.
//
// The same deployment also serves a public read-only demo: the demo button on
// the login screen starts a guest session (GET-only, private data replaced
// with sample content), so one Space serves both the founder and the public.

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
  // "legacy" until the server says otherwise: wrongly assuming real accounts
  // would label the box "Email address" on a deployment that wants a username.
  const [identityMode, setIdentityMode] = useState<"identity" | "legacy">("legacy");
  const [guest, setGuest] = useState(false);
  // True while the host isn't answering. Nothing is decided in that state -
  // no sign-out, no guessing - the check just runs again shortly.
  const [outage, setOutage] = useState(false);
  const [attempt, setAttempt] = useState(0);

  const probe = useCallback(async (): Promise<"done" | "retry"> => {
    const status = await api.authStatus();
    if (!status) return "retry";
    setDemo(status.demo);
    setGuestAvailable(status.guest_available !== false);
    setIdentityMode(status.identity?.mode === "identity" ? "identity" : "legacy");

    // A subscriber opens their own cockpit (reading /api/me), whatever the
    // founder gate is set to. A session the server rejects is cleared and
    // falls through to the sign-in screen.
    if (getCustomerToken()) {
      const check = await verifyCustomer();
      if (check === "unreachable") return "retry";
      if (check === "ok") {
        markGuest(false);
        setGuest(false);
        setState("ready");
        return "done";
      }
    }

    // A whole-Space guest deploy (legacy TITAN_GUEST_MODE) needs no login.
    if (status.guest) {
      markGuest(true);
      setGuest(true);
      setState("ready");
      return "done";
    }

    if (!status.required) {
      setState("ready");
      return "done";
    }

    const token = getToken();
    if (!token) {
      setState("login");
      return "done";
    }

    // Verify the stored token really works; only a token the server rejects
    // is dropped, never one it simply didn't get to answer about.
    const check = await verifyToken();
    if (check === "unreachable") return "retry";
    if (check === "invalid") {
      setToken(null);
      markGuest(false);
      setState("login");
      return "done";
    }
    // Ask the server what this token is instead of guessing from
    // sessionStorage - in a new tab a restored demo token could otherwise be
    // shown as the founder while still getting sample data.
    const kind = await api.sessionKind();
    if (!kind) return "retry";
    markGuest(kind.guest);
    setGuest(kind.guest);
    setState("ready");
    return "done";
  }, []);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    void probe().then((result) => {
      if (cancelled) return;
      if (result === "retry") {
        setOutage(true);
        timer = setTimeout(() => setAttempt((n) => n + 1), 4000);
      } else {
        setOutage(false);
      }
    });
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [probe, attempt]);

  if (state === "loading") {
    // This is what a crawler sees: the app is client-rendered, so the static
    // export prerenders exactly this state. It needs a real heading and links
    // (including the privacy policy) or Titan's own audit would flag the page.
    //
    // The content is real and visible, not markup hidden for robots - a visitor
    // on a slow connection sees it too.
    return (
      <main className="flex min-h-screen flex-col items-center justify-center px-6 text-center">
        <h1 className="font-mono text-2xl font-semibold tracking-wide text-white">
          TITAN<span className="text-hud-cyan"> OMEGA</span>
        </h1>
        <p className="mt-3 max-w-lg text-sm text-slate-400">
          Your AI business command centre. Titan Omega finds leads and drafts
          your outreach, writes your posts, answers you by voice in 12
          languages, scans your market, tracks your revenue, and watches your
          website for SEO and legal risk around the clock.
        </p>
        <span className="mt-6 animate-pulseGlow font-mono text-xs text-hud-cyan">
          Booting the command centre…
        </span>
        {outage && (
          <p className="mt-3 max-w-md text-xs text-hud-amber">
            Titan&apos;s server isn&apos;t answering right now - our hosting provider
            is having a brief outage. Retrying automatically; you&apos;re still
            signed in.
          </p>
        )}
        <nav className="mt-8 flex flex-wrap items-center justify-center gap-x-5 gap-y-2 text-xs text-slate-500">
          <a className="hover:text-hud-cyan" href="/pricing">Pricing</a>
          <a className="hover:text-hud-cyan" href="/privacy">Privacy</a>
          <a className="hover:text-hud-cyan" href="/terms">Terms</a>
          <a className="hover:text-hud-cyan" href="/refunds">Refunds</a>
          <a className="hover:text-hud-cyan" href="mailto:rathoreabdullah816@gmail.com">Contact</a>
          <a className="hover:text-hud-cyan" href="/portal">Client portal</a>
        </nav>
      </main>
    );
  }
  if (state === "login") {
    return (
      <Login
        demo={demo}
        identityMode={identityMode}
        guestAvailable={guestAvailable}
        onSuccess={() => {
          markGuest(false);
          setGuest(false);
          setState("ready");
        }}
      />
    );
  }
  const signOut = () => {
    setToken(null);
    setCustomerToken(null);
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
