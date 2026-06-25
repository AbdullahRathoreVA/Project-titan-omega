"use client";

import { useState } from "react";
import { Hexagon, Lock } from "lucide-react";
import { api } from "@/lib/api";

export function Login({ onSuccess, demo }: { onSuccess: () => void; demo: boolean }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    const ok = await api.login(username.trim(), password);
    setBusy(false);
    if (ok) onSuccess();
    else setError("Invalid username or password.");
  }

  return (
    <main className="flex min-h-screen items-center justify-center px-4">
      <form onSubmit={submit} className="panel w-full max-w-sm p-6 shadow-glow">
        <div className="mb-5 flex items-center gap-3">
          <div className="relative">
            <Hexagon className="h-9 w-9 text-hud-cyan" strokeWidth={1.4} />
            <span className="absolute inset-0 flex items-center justify-center text-[10px] font-bold text-hud-cyan">
              ΤΩ
            </span>
          </div>
          <div>
            <h1 className="font-mono text-lg font-semibold tracking-wide text-white">
              TITAN<span className="text-hud-cyan"> OMEGA</span>
            </h1>
            <p className="text-[11px] text-slate-500">Empire Command Center · sign in</p>
          </div>
        </div>

        <label className="hud-label">Username</label>
        <input
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          autoComplete="username"
          className="mt-1 mb-3 w-full rounded-lg border border-edge bg-panel-2/60 px-3 py-2 text-sm text-slate-100 focus:border-hud-cyan/40 focus:outline-none"
        />

        <label className="hud-label">Password</label>
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoComplete="current-password"
          className="mt-1 mb-4 w-full rounded-lg border border-edge bg-panel-2/60 px-3 py-2 text-sm text-slate-100 focus:border-hud-cyan/40 focus:outline-none"
        />

        {error && <p className="mb-3 text-xs text-hud-rose">{error}</p>}

        <button
          type="submit"
          disabled={busy}
          className="flex w-full items-center justify-center gap-2 rounded-lg border border-hud-cyan/40 bg-hud-cyan/10 py-2 text-sm font-medium text-hud-cyan transition-colors hover:bg-hud-cyan/20 disabled:opacity-50"
        >
          <Lock className="h-4 w-4" />
          {busy ? "Signing in…" : "Enter command center"}
        </button>

        {demo && (
          <p className="mt-4 text-[11px] leading-relaxed text-hud-amber">
            ⚠ Demo login (founder / titan). Set TITAN_USERNAME and TITAN_PASSWORD on
            your host to secure it — never commit your password to the repo.
          </p>
        )}
      </form>
    </main>
  );
}
