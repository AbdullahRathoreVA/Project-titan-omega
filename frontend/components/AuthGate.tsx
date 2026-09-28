"use client";

import { useCallback, useEffect, useState } from "react";
import { LogOut } from "lucide-react";
import { api, getToken, setToken, verifyCustomer, verifyToken } from "@/lib/api";
import { getCustomerToken, setCustomerToken } from "@/lib/session";
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
  // "legacy" until the server says otherwise: assuming real accounts and then
  // being wrong would label the box "Email address" on a deployment that wants
  // a username, which is a login nobody can complete.
  const [identityMode, setIdentityMode] = useState<"identity" | "legacy">("legacy");
  const [guest, setGuest] = useState(false);

  const probe = useCallback(async () => {
    const status = await api.authStatus();
    setDemo(status.demo);
    setGuestAvailable(status.guest_available !== false);
    setIdentityMode(status.identity?.mode === "identity" ? "identity" : "legacy");

    // A subscriber opens their own cockpit (reading /api/me), whatever the
    // founder gate is set to. A stale session is cleared and falls through
    // to the sign-in screen.
    if (getCustomerToken()) {
      if (await verifyCustomer()) {
        markGuest(false);
        setGuest(false);
        setState("ready");
        return;
      }
      setCustomerToken(null);
    }

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
      // Ask the server what this token actually is. Guessing from
      // sessionStorage broke in a new tab: a restored DEMO token was shown as
      // the founder while still being served sample data.
      const kind = await api.sessionKind();
      markGuest(kind.guest);
      setGuest(kind.guest);
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
    // This is what a CRAWLER sees. The app is client-rendered, so the static
    // export prerenders exactly this state — and it used to contain only the
    // words "Booting Titan Omega…", no heading and no links. Titan's own audit
    // reported the resulting page as having an H1 problem and no privacy
    // policy linked, which is the same finding it charges clients to fix.
    //
    // The content below is real and visible, not markup hidden for robots:
    // a visitor on a slow connection sees this too, and every claim in it is
    // accurate.
    return (
      <main className="flex min-h-screen flex-col items-center justify-center px-6 text-center">
        <h1 className="font-mono text-2xl font-semibold tracking-wide text-white">
          TITAN<span className="text-hud-cyan"> OMEGA</span>
        </h1>
        <p className="mt-3 max-w-lg text-sm text-slate-400">
          SEO, local ranking and legal compliance audits for any business, in
          any jurisdiction. Technical, local and legal findings are scored
          separately — never averaged into one number that hides the expensive
          one.
        </p>
        <span className="mt-6 animate-pulseGlow font-mono text-xs text-hud-cyan">
          Booting the command centre…
        </span>
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
