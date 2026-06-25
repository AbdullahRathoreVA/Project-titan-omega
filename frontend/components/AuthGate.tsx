"use client";

import { useCallback, useEffect, useState } from "react";
import { api, getToken } from "@/lib/api";
import { Login } from "./Login";
import { CommandCenter } from "./CommandCenter";

// Decides whether to show the login screen or the dashboard. When the core does
// not require auth (local dev), it goes straight to the dashboard.
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
    // Auth required: a stored token lets us in; the dashboard's first calls will
    // 401 and fall back gracefully if it's stale, prompting a fresh login.
    setState(getToken() ? "ready" : "login");
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
