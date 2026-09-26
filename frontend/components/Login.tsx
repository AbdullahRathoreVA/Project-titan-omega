"use client";

/**
 * The front door.
 *
 * This used to be a bare username/password box. That meant a stranger landing
 * on titanomega-ai.com could not sign up, could not see a price, and could not
 * buy anything — the signup flow at /join existed but nothing on the site
 * linked to it. For a product whose problem is revenue, that was the most
 * expensive bug in the codebase.
 *
 * The order below is deliberate and reflects who actually arrives here:
 *   1. Strangers, who need a price and a way in  → plans + "Start free"
 *   2. People evaluating it                      → live demo
 *   3. Abdullah                                  → sign in, tucked away
 *
 * Prices are FETCHED from /api/plans, never hardcoded. A landing page that
 * disagrees with what the server charges is how someone ends up billed for
 * something they were never shown.
 */

import { useEffect, useState } from "react";
import { Hexagon, Lock, PlayCircle, ArrowRight, Check } from "lucide-react";
import { api } from "@/lib/api";

type Plan = {
  key: string;
  name: string;
  price_usd: number;
  limits: { clients: number; audits_per_month: number };
  features: string[];
  /** How many days this plan's trial runs, straight from the server.
   *  `billing.trial_days()` owns this and it is overridable per plan by
   *  environment variable without a deploy, so it is never written here — a
   *  page that says "free for 10 days" while the server grants 7 is a promise
   *  nobody made. Same rule as the prices above. */
  trial_days?: number;
  /** Whether that trial can actually convert into a subscription. False while
   *  no payment processor is connected, which is the case today. */
  trial_billable?: boolean;
};

export function Login({
  onSuccess,
  demo,
  identityMode = "legacy",
  guestAvailable = true,
  onGuest,
}: {
  onSuccess: () => void;
  demo: boolean;
  /** Which login the server is actually running. Under real accounts this box
   *  wants an email address; under the old environment gate it wants a
   *  username. Labelling it wrongly is a sign-in nobody can complete, so the
   *  label comes from /api/auth rather than from an assumption here. */
  identityMode?: "identity" | "legacy";
  guestAvailable?: boolean;
  onGuest?: () => void;
}) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [guestBusy, setGuestBusy] = useState(false);
  const [productBusy, setProductBusy] = useState(false);
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
    const who = await api.login(username.trim(), password);
    setBusy(false);
    if (who === "founder") {
      onSuccess();
    } else if (who === "account") {
      // A real customer, at the owner's door. Their session is already stored
      // under the key /join reads, so this is a redirect and not a second
      // password prompt. Sending them into the founder dashboard instead
      // would show them somebody else's business.
      window.location.href = "/join";
    } else {
      setError(
        identityMode === "identity"
          ? "Invalid email or password."
          : "Invalid username or password.",
      );
    }
  }

  /** Open the CUSTOMER product — what somebody actually receives when they
   *  pay. This is the primary demo, and it exists because the other one was
   *  selling something no customer could be given. The dashboard at / is the
   *  founder's own console; a prospect who saw it and then subscribed got
   *  /portal, which is a different product. Reported live, in those words:
   *  "I made an enterprise account but I cannot open it the way it is shown
   *  in the demo."
   *
   *  The server picks the business and the token is a normal portal session,
   *  so this shows the real screen against a real audit rather than a mockup
   *  of one. */
  async function startProductDemo() {
    setProductBusy(true);
    setError("");
    try {
      const res = await fetch("/api/demo/portal", { method: "POST" });
      if (!res.ok) {
        setError("The product demo is unavailable right now.");
        return;
      }
      const data = (await res.json()) as { token: string };
      // The key /portal reads. Same origin, so this survives the navigation.
      sessionStorage.setItem("client_token", data.token);
      window.location.href = "/portal";
    } catch {
      setError("The product demo is unavailable right now.");
    } finally {
      setProductBusy(false);
    }
  }

  /** The OPERATOR console tour. Deliberately secondary and deliberately
   *  labelled: this is Titan's own cockpit with sample figures, not the
   *  customer product. Kept because it is worth showing, removed from the
   *  primary position because presenting it as "the demo" was the lie. */
  async function startDemo() {
    setGuestBusy(true);
    setError("");
    const ok = await api.enterDemo();
    setGuestBusy(false);
    if (ok) onGuest?.();
    else setError("Demo is unavailable right now.");
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

          {/* The product demo. Primary, because it is the only one that shows
              what a customer receives. */}
          <button
            type="button"
            onClick={startProductDemo}
            disabled={productBusy}
            className="flex w-full max-w-sm items-center justify-center gap-2 rounded-lg border border-hud-cyan/45 bg-hud-cyan/10 py-2.5 text-sm font-medium text-hud-cyan transition-colors hover:bg-hud-cyan/20 disabled:opacity-50"
          >
            <PlayCircle className="h-4 w-4" />
            {productBusy ? "Opening…" : "See the product — a real audit, no signup"}
          </button>

          {guestAvailable && (
            <button
              type="button"
              onClick={startDemo}
              disabled={guestBusy}
              className="text-[11px] text-slate-500 underline-offset-2 transition-colors hover:text-hud-violet hover:underline disabled:opacity-50"
            >
              {guestBusy
                ? "Starting…"
                : "Or tour the operator console (our internal view, sample figures)"}
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
            <button
              type="button"
              onClick={() => setShowSignIn((v) => !v)}
              className="hover:text-hud-cyan"
            >
              {showSignIn ? "Hide sign in" : "Sign in"}
            </button>
          </div>

          {/* Payment honesty, at the point of decision rather than at checkout.
              Free works regardless; hiding this until the last screen would be
              the dark pattern the pricing spec forbids. */}
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
