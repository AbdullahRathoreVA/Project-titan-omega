"use client";

import { useCallback, useEffect, useState } from "react";
import { api, getToken, setToken, verifyToken } from "@/lib/api";
import { Login } from "./Login";
import { CommandCenter } from "./CommandCenter";

// Decides whether to show the login screen or the dashboard. When the core does
// not require auth (local dev / auth disabled), it goes straight to the
// dashboard. When auth IS required, we VERIFY the stored token actually works
// before trusting it — otherwise a stale token (e.g. after changing the
// username/password) would silently trap the dashboard in 401/demo mode.
export function AuthGate() {
  const [state, setState] = useState<"loading" | "login" | "ready">("loading");
  const [demo, setDemo] = useState(true);

  const probe = useCallback(async () => {
    const status = await api.authStatus();
    setDemo(status.demo);

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
      setState("ready");
    } else {
      setToken(null);
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
    return <Login demo={demo} onSuccess={() => setState("ready")} />;
  }
  return <CommandCenter />;
}
