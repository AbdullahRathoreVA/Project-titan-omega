"use client";

/**
 * The front door.
 *
 * A stranger landing on titanomega-ai.com needs to see a price and be able to
 * sign up and buy, not just a sign-in box. The order reflects who arrives:
 *   1. Strangers, who need a price and a way in  -> plans + "Start free"
 *   2. People evaluating it                      -> live demo
 *   3. The founder                               -> sign in, tucked away
 *
 * Prices are fetched from /api/plans, never hardcoded, so the page can't
 * disagree with what the server charges.
 */

import { useEffect, useState } from "react";
import { Hexagon, Lock, PlayCircle, ArrowRight, Check } from "lucide-react";
import { api, enterCockpitDemo } from "@/lib/api";

type Plan = {
  key: string;
  name: string;
  price_usd: number;
  limits: { clients: number; audits_per_month: number };
  features: string[];
  /**
   * How many days this plan's trial runs, from the server.
   * `billing.trial_days()` owns this and it can be overridden per plan by
   * environment variable without a deploy, so it's never written here.
   */
  trial_days?: number;
  /**
   * Whether the trial can actually convert into a subscription. False while
   * no payment processor is connected.
   */
  trial_billable?: boolean;
};

export function Login({
  onSuccess,
  demo,
  identityMode = "legacy",
  guestAvailable = true,
}: {
  onSuccess: () => void;
  demo: boolean;
  /**
   * Which login the server is running. Under real accounts this box wants an
   * email address; under the old environment gate, a username. The label
   * comes from /api/auth so it's never wrong.
   */
  identityMode?: "identity" | "legacy";
  guestAvailable?: boolean;
}) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [demoBusy, setDemoBusy] = useState(false);
  const [showSignIn, setShowSignIn] = useState(false);
  const [plans, setPlans] = useState<Plan[]>([]);
  const [processor, setProcessor] = useState<string>("");

  useEffect(() => {
    fetch("/api/plans", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (d?.plans) setPlans(d.plans);
        if (d?.processor) setProcessor(d.processor);
      })
      .catch(() => {
        /* the page still works without prices; it just cannot show them */
      });
  }, []);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    let who: Awaited<ReturnType<typeof api.login>> = null;
    try {
      who = await api.login(username.trim(), password);
    } catch {
      setBusy(false);
      setError("Could not reach Titan. Check your connection and try again.");
      return;
    }
    setBusy(false);
    if (who === "limited") {
      setError("Too many sign-in attempts. Please wait a few minutes and try again.");
    } else if (who === "unreachable") {
      setError(
        "Titan's server didn't answer - our hosting provider is having a brief " +
          "outage. Your password wasn't rejected; please try again in a minute.",
      );
    } else if (who === "founder") {
      onSuccess();
    } else if (who === "account") {
      // A subscriber gets their own cockpit: the same screens, reading only
      // their workspace through /api/me (see lib/session.ts).
      onSuccess();
    } else {
      setError(
        identityMode === "identity"
          ? "Invalid email or password."
          : "Invalid username or password.",
      );
    }
  }

  /**
   * The demo is the cockpit a subscriber actually gets - every tab, the boot,
   * the voice, the 3D universe - on a read-only demo account holding Titan's
   * own demonstration businesses.
   */
  async function startCockpitDemo() {
    setDemoBusy(true);
    setError("");
    const result = await enterCockpitDemo();
    setDemoBusy(false);
    if (result === "ok") onSuccess();
    else if (result === "unreachable") {
      setError(
        "Titan's server didn't answer - our hosting provider is having a brief " +
          "outage. Please try again in a minute.",
      );
    } else setError("The demo is unavailable right now.");
  }

  const limitLine = (p: Plan) => {
    const c = p.limits.clients;
    const a = p.limits.audits_per_month;
    return `${c === -1 ? "Unlimited" : c} business${c === 1 ? "" : "es"} · ${
      a === -1 ? "unlimited" : a
    } audits/mo`;
  };

  return (
    <main className="min-h-screen px-4 py-10">
      <div className="mx-auto w-full max-w-4xl">
        <header className="mb-8 text-center">
          <div className="mb-4 flex items-center justify-center gap-3">
            <div className="relative">
              <Hexagon className="h-9 w-9 text-hud-cyan" strokeWidth={1.4} />
              <span className="absolute inset-0 flex items-center justify-center text-[10px] font-bold text-hud-cyan">
                ΤΩ
              </span>
            </div>
            <h1 className="font-mono text-xl font-semibold tracking-wide text-white">
              TITAN<span className="text-hud-cyan"> OMEGA</span>
            </h1>
          </div>
          <h2 className="mx-auto max-w-2xl text-balance text-2xl font-semibold leading-tight text-slate-100 sm:text-3xl">
            SEO, local ranking and legal compliance — audited for any business,
            in any jurisdiction
          </h2>
          <p className="mx-auto mt-3 max-w-xl text-sm leading-relaxed text-slate-400">
            Add your website and get a full technical, local and legal audit in
            under a minute. The free tier includes the legal findings in full.
          </p>
        </header>

        {/* Plans first — a stranger needs a price before anything else. */}
        {plans.length > 0 && (
          <div className="mb-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {plans.map((p) => (
              <div
                key={p.key}
                className={`rounded-xl border p-4 ${
                  p.key === "individual"
                    ? "border-hud-cyan/45 bg-hud-cyan/5 shadow-glow"
                    : "border-edge bg-panel"
                }`}
              >
                <div className="text-[10px] uppercase tracking-widest text-slate-500">
                  {p.name}
                </div>
                {(p.trial_days ?? 0) > 0 && (
                  <div className="mt-1.5 inline-block rounded border border-hud-emerald/40 bg-hud-emerald/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-hud-emerald">
                    Free for {p.trial_days} {p.trial_days === 1 ? "day" : "days"}
                  </div>
                )}
                <div className="mt-1 font-mono text-2xl font-semibold text-white">
                  ${p.price_usd}
                  <span className="ml-1 text-[11px] font-normal text-slate-500">
                    /mo
                  </span>
                </div>
                <div className="mt-2 text-[10.5px] leading-relaxed text-slate-400">
                  {limitLine(p)}
                </div>
                <ul className="mt-3 space-y-1">
                  {p.features.slice(0, 3).map((f) => (
                    <li key={f} className="flex gap-1.5 text-[10.5px] text-slate-400">
                      <Check className="mt-0.5 h-3 w-3 shrink-0 text-hud-emerald" />
                      <span>{f}</span>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        )}

        {/* The primary action. /join is the real signup flow: account → plan →
            business → first audit → PDF. */}
        <div className="flex flex-col items-center gap-3">
          <a
            href="/join"
            className="flex w-full max-w-sm items-center justify-center gap-2 rounded-lg border border-hud-emerald/45 bg-hud-emerald/10 py-3 text-sm font-semibold text-hud-emerald transition-colors hover:bg-hud-emerald/20"
          >
            Start free — no card needed <ArrowRight className="h-4 w-4" />
          </a>

          {/* The demo: the subscriber cockpit itself, read-only. */}
          {guestAvailable && (
            <button
              type="button"
              onClick={startCockpitDemo}
              disabled={demoBusy}
              className="flex w-full max-w-sm items-center justify-center gap-2 rounded-lg border border-hud-cyan/45 bg-hud-cyan/10 py-2.5 text-sm font-medium text-hud-cyan transition-colors hover:bg-hud-cyan/20 disabled:opacity-50"
            >
              <PlayCircle className="h-4 w-4" />
              {demoBusy ? "Opening…" : "Try the cockpit — no signup"}
            </button>
          )}

          <div className="flex gap-4 text-[11px] text-slate-500">
            <a href="/pricing" className="hover:text-hud-cyan">
              Compare plans
            </a>
            <a href="/privacy" className="hover:text-hud-cyan">
              Privacy
            </a>
            <a href="/terms" className="hover:text-hud-cyan">
              Terms
            </a>
            <a href="/refunds" className="hover:text-hud-cyan">
              Refunds
            </a>
            <a href="mailto:rathoreabdullah816@gmail.com" className="hover:text-hud-cyan">
              Contact
            </a>
            <button
              type="button"
              onClick={() => setShowSignIn((v) => !v)}
              className="hover:text-hud-cyan"
            >
              {showSignIn ? "Hide sign in" : "Sign in"}
            </button>
          </div>

          {/* Say it at the point of decision rather than at checkout. Free
              works regardless; hiding this until the last screen would be a
              dark pattern. */}
          {processor === "none" && plans.length > 0 && (
            <p className="max-w-md text-center text-[10px] leading-relaxed text-hud-amber">
              Paid plans cannot be completed yet — no payment processor is
              connected. The free tier is fully usable and includes the legal
              findings.
            </p>
          )}
        </div>

        {/* Owner sign-in, deliberately last. */}
        {showSignIn && (
          <form
            onSubmit={submit}
            className="panel mx-auto mt-6 w-full max-w-sm p-5"
          >
            <p className="mb-3 text-[11px] text-slate-500">
              Account holders and the owner sign in here. Customers are taken
              to their own workspace.
            </p>
            <label className="hud-label">
              {identityMode === "identity" ? "Email address" : "Username"}
            </label>
            <input
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              type={identityMode === "identity" ? "email" : "text"}
              inputMode={identityMode === "identity" ? "email" : "text"}
              autoComplete={identityMode === "identity" ? "email" : "username"}
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
              <p className="mt-3 text-[11px] leading-relaxed text-hud-amber">
                ⚠ Demo login (founder / titan). Set TITAN_USERNAME and
                TITAN_PASSWORD on your host to secure it.
              </p>
            )}
            {!demo && identityMode === "legacy" && (
              <p className="mt-3 text-[11px] leading-relaxed text-slate-500">
                Signing in against the environment gate. Set
                TITAN_FOUNDER_EMAIL to move to a real account with a hashed
                password — the gate switches itself off once one exists.
              </p>
            )}
          </form>
        )}
      </div>
    </main>
  );
}
