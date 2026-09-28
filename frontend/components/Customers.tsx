"use client";

/**
 * Customers - the founder's account list, and the form that creates one.
 *
 * The screen for `POST /api/founder/accounts`. Three rules:
 *
 * 1. A failed fetch isn't an empty customer list. State starts `null` and
 *    only becomes an array once a response arrives, so a 403 shows "could not
 *    load" rather than "no customers yet".
 * 2. A granted seat isn't a paying customer. Grants get their own column and
 *    count, and nothing here implies revenue while no payment processor is
 *    configured.
 * 3. The generated password is shown exactly once. It's stored only as a
 *    PBKDF2 hash, so this is the only moment it can be read, and the screen
 *    says so.
 */

import { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  Check,
  Copy,
  RefreshCw,
  UserPlus,
  Users,
} from "lucide-react";

type AccountRow = {
  email: string;
  plan: string;
  plan_name: string;
  price_usd: number;
  status: string;
  paying: boolean;
  granted: boolean;
  grant_note: string;
  days_since_signup: number;
  usage: Record<string, number>;
  business_count: number;
  businesses: { business_name: string; website: string }[];
  days_since_seen: number | null;
};

type PlanOption = { key: string; name: string; price_usd: number };

type CustomerList = {
  accounts: AccountRow[];
  counts: {
    total: number;
    paying: number;
    granted_paid_plans: number;
    by_plan: Record<string, number>;
    by_status: Record<string, number>;
  };
  plans: PlanOption[];
  processor: string;
  billable: boolean;
  storage_warning: string | null;
};

type GrantResult = {
  account: { email: string; plan: string; status: string };
  created: boolean;
  password: string | null;
  note: string;
};

function token(): string {
  if (typeof window === "undefined") return "";
  return (
    localStorage.getItem("titan_token") ||
    sessionStorage.getItem("titan_token") ||
    ""
  );
}

/**
 * GET that returns null on any failure, so the caller can tell "no answer"
 * from "an empty answer".
 */
async function load<T>(path: string): Promise<T | null> {
  try {
    const r = await fetch(`/api${path}`, {
      cache: "no-store",
      headers: { Authorization: `Bearer ${token()}` },
    });
    if (!r.ok) return null;
    return (await r.json()) as T;
  } catch {
    return null;
  }
}

/**
 * POST that keeps the server's reason, so a message like "A valid email
 * address is required" reaches the founder instead of a bare "failed".
 */
async function send<T>(
  path: string,
  body: unknown,
): Promise<{ ok: true; data: T } | { ok: false; error: string }> {
  try {
    const r = await fetch(`/api${path}`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token()}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(body),
    });
    const text = await r.text();
    if (!r.ok) {
      let detail = `HTTP ${r.status}`;
      try {
        const parsed = JSON.parse(text) as { detail?: string };
        if (parsed.detail) detail = parsed.detail;
      } catch {
        /* a non-JSON error body: the status is all there is */
      }
      return { ok: false, error: detail };
    }
    return { ok: true, data: JSON.parse(text) as T };
  } catch {
    return { ok: false, error: "Could not reach Titan." };
  }
}

export default function Customers() {
  const [list, setList] = useState<CustomerList | null>(null);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState(false);

  const [email, setEmail] = useState("");
  const [plan, setPlan] = useState("enterprise");
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  const [result, setResult] = useState<GrantResult | null>(null);
  const [copied, setCopied] = useState(false);

  const refresh = useCallback(async () => {
    const data = await load<CustomerList>("/founder/accounts");
    setFailed(data === null);
    if (data) setList(data);
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const create = async () => {
    if (busy || !email.trim()) return;
    setBusy(true);
    setError("");
    setResult(null);
    setCopied(false);
    const res = await send<GrantResult>("/founder/accounts", {
      email: email.trim(),
      plan,
      note: note.trim(),
    });
    if (res.ok) {
      setResult(res.data);
      setEmail("");
      setNote("");
      await refresh();
    } else {
      setError(res.error);
    }
    setBusy(false);
  };

  const changePlan = async (target: string, nextPlan: string) => {
    setError("");
    const res = await send<unknown>(
      `/founder/accounts/${encodeURIComponent(target)}/plan`,
      { email: target, plan: nextPlan },
    );
    if (!res.ok) setError(res.error);
    await refresh();
  };

  const copyPassword = async () => {
    if (!result?.password) return;
    try {
      await navigator.clipboard.writeText(result.password);
      setCopied(true);
    } catch {
      // Clipboard is blocked outside a secure context. The password is on screen
      // and selectable, so this is only a convenience.
      setCopied(false);
    }
  };

  const plans: PlanOption[] = list?.plans ?? [];

  return (
    <div className="space-y-4">
      {/* create ------------------------------------------------------------ */}
      <section className="panel">
        <header className="panel-header">
          <div className="flex items-center gap-2">
            <UserPlus className="h-4 w-4 text-hud-emerald" strokeWidth={1.6} />
            <h2 className="text-sm font-medium text-slate-200">Add a customer</h2>
          </div>
          <span className="hud-label">creates a real account · bypasses payment</span>
        </header>

        <div className="space-y-3 p-3">
          <div className="flex flex-wrap gap-2">
            <input
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && void create()}
              placeholder="their@email.com"
              type="email"
              className="min-w-[220px] flex-1 rounded-lg border border-edge bg-panel/80 px-3 py-2 text-sm text-slate-200 placeholder:text-slate-600 focus:border-hud-cyan/50 focus:outline-none"
            />
            <select
              value={plan}
              onChange={(e) => setPlan(e.target.value)}
              className="rounded-lg border border-edge bg-panel/80 px-3 py-2 text-sm text-slate-200 focus:border-hud-cyan/50 focus:outline-none"
            >
              {/* Read from billing.PLANS server-side, so this cannot offer a
                  plan the POST would refuse with a 400. */}
              {plans.length === 0 ? (
                <option value="enterprise">enterprise</option>
              ) : (
                plans.map((p) => (
                  <option key={p.key} value={p.key}>
                    {p.name}
                    {p.price_usd > 0 ? ` — $${p.price_usd}/mo` : ""}
                  </option>
                ))
              )}
            </select>
          </div>
          <div className="flex flex-wrap gap-2">
            <input
              value={note}
              onChange={(e) => setNote(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && void create()}
              placeholder="note — why this seat was granted (recorded on the account)"
              className="min-w-[220px] flex-1 rounded-lg border border-edge bg-panel/80 px-3 py-2 text-sm text-slate-200 placeholder:text-slate-600 focus:border-hud-cyan/50 focus:outline-none"
            />
            <button
              onClick={() => void create()}
              disabled={busy || !email.trim()}
              className="min-h-11 shrink-0 rounded-lg border border-hud-emerald/40 bg-hud-emerald/10 px-4 text-sm text-hud-emerald transition-colors hover:bg-hud-emerald/20 disabled:cursor-not-allowed disabled:opacity-40 sm:min-h-0 sm:py-2"
            >
              {busy ? "Creating…" : "Create account"}
            </button>
          </div>

          {error && (
            <div className="flex items-start gap-2 rounded-lg border border-hud-rose/30 bg-hud-rose/5 p-2 text-xs text-hud-rose">
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          {result && (
            <div className="space-y-2 rounded-lg border border-hud-cyan/30 bg-hud-cyan/5 p-3">
              <div className="text-xs text-slate-300">
                <span className="font-medium text-hud-cyan">
                  {result.account.email}
                </span>{" "}
                is on <span className="text-slate-100">{result.account.plan}</span>,
                status {result.account.status}.
              </div>
              {result.password ? (
                <div className="space-y-1">
                  <div className="hud-label">
                    password — shown once, stored only as a hash
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <code className="select-all rounded border border-edge bg-black/40 px-2 py-1 font-mono text-sm text-hud-amber">
                      {result.password}
                    </code>
                    <button
                      onClick={() => void copyPassword()}
                      className="flex items-center gap-1 rounded border border-edge px-2 py-1 text-[11px] text-slate-400 hover:text-slate-200"
                    >
                      {copied ? (
                        <>
                          <Check className="h-3 w-3" /> copied
                        </>
                      ) : (
                        <>
                          <Copy className="h-3 w-3" /> copy
                        </>
                      )}
                    </button>
                  </div>
                </div>
              ) : null}
              <div className="text-[11px] leading-relaxed text-slate-500">
                {result.note}
              </div>
            </div>
          )}
        </div>
      </section>

      {/* list -------------------------------------------------------------- */}
      <section className="panel">
        <header className="panel-header">
          <div className="flex items-center gap-2">
            <Users className="h-4 w-4 text-hud-cyan" strokeWidth={1.6} />
            <h2 className="text-sm font-medium text-slate-200">Customers</h2>
          </div>
          <button
            onClick={() => void refresh()}
            className="flex items-center gap-1 text-[11px] text-slate-500 hover:text-slate-300"
          >
            <RefreshCw className="h-3 w-3" /> refresh
          </button>
        </header>

        <div className="p-3">
          {list === null ? (
            <div className="py-6 text-center text-xs text-slate-500">
              {/* Never "no customers yet" on a failure — that is a measured
                  claim about the business made from a network error. */}
              {failed
                ? "Could not load the customer list. This screen is founder-only; a demo session gets 403."
                : "loading…"}
            </div>
          ) : (
            <>
              <div className="mb-3 grid grid-cols-3 gap-2">
                {[
                  ["Accounts", String(list.counts.total), "text-white"],
                  ["Paying", String(list.counts.paying), "text-hud-emerald"],
                  [
                    "Granted seats",
                    String(list.counts.granted_paid_plans),
                    "text-hud-amber",
                  ],
                ].map(([label, value, tone]) => (
                  <div
                    key={label}
                    className="rounded-lg border border-edge bg-panel/60 p-2"
                  >
                    <div className="hud-label">{label}</div>
                    <div className={`font-mono text-lg ${tone}`}>{value}</div>
                  </div>
                ))}
              </div>

              {!list.billable && (
                <div className="mb-3 flex items-start gap-2 text-[10px] leading-relaxed text-slate-500">
                  <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0 text-hud-amber" />
                  <span>
                    No payment processor is configured ({list.processor}), so
                    nothing on this screen has been charged. A granted seat is
                    counted separately from a paying customer for exactly that
                    reason.
                  </span>
                </div>
              )}

              {list.accounts.length === 0 ? (
                <div className="py-6 text-center text-xs text-slate-500">
                  No accounts yet. The form above creates one.
                </div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[720px] text-left text-[11px]">
                    <thead className="text-[10px] uppercase tracking-widest text-slate-600">
                      <tr>
                        <th className="pb-2 font-normal">Email</th>
                        <th className="pb-2 font-normal">Plan</th>
                        <th className="pb-2 font-normal">Status</th>
                        <th className="pb-2 font-normal">Businesses</th>
                        <th className="pb-2 font-normal">Audits</th>
                        <th className="pb-2 font-normal">Signed up</th>
                        <th className="pb-2 font-normal">Last seen</th>
                        <th className="pb-2 font-normal">Change plan</th>
                      </tr>
                    </thead>
                    <tbody className="text-slate-300">
                      {list.accounts.map((a) => (
                        <tr key={a.email} className="border-t border-white/5">
                          <td className="py-2 pr-3 font-mono text-slate-200">
                            {a.email}
                          </td>
                          <td className="py-2 pr-3">
                            <span
                              className={
                                a.paying ? "text-hud-emerald" : "text-slate-400"
                              }
                            >
                              {a.plan_name}
                            </span>
                            {a.granted && (
                              <span
                                className="ml-1 text-hud-amber"
                                title={
                                  a.grant_note
                                    ? `Granted: ${a.grant_note}. Never charged.`
                                    : "Granted by the founder. Never charged."
                                }
                              >
                                granted
                              </span>
                            )}
                          </td>
                          <td className="py-2 pr-3">
                            <span
                              className={
                                a.status === "active"
                                  ? "text-slate-300"
                                  : "text-hud-amber"
                              }
                            >
                              {a.status}
                            </span>
                          </td>
                          <td className="py-2 pr-3">
                            {a.business_count === 0 ? (
                              <span className="text-hud-rose">none</span>
                            ) : (
                              <span
                                title={a.businesses
                                  .map((b) => b.business_name)
                                  .join(", ")}
                              >
                                {a.business_count}
                              </span>
                            )}
                          </td>
                          <td className="py-2 pr-3 text-slate-400">
                            {a.usage.audits ?? 0}
                          </td>
                          <td className="py-2 pr-3 text-slate-500">
                            {a.days_since_signup}d ago
                          </td>
                          <td className="py-2 pr-3">
                            {a.days_since_seen === null ? (
                              <span
                                className="text-hud-rose"
                                title="Signed up and never came back"
                              >
                                never returned
                              </span>
                            ) : (
                              <span className="text-slate-500">
                                {a.days_since_seen}d ago
                              </span>
                            )}
                          </td>
                          <td className="py-2 pr-3">
                            <select
                              value={a.plan}
                              onChange={(e) =>
                                void changePlan(a.email, e.target.value)
                              }
                              className="rounded border border-edge bg-panel/80 px-1.5 py-1 text-[11px] text-slate-300 focus:border-hud-cyan/50 focus:outline-none"
                            >
                              {plans.map((p) => (
                                <option key={p.key} value={p.key}>
                                  {p.name}
                                </option>
                              ))}
                            </select>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {list.storage_warning && (
                <div className="mt-3 flex items-start gap-2 text-[10px] leading-relaxed text-slate-500">
                  <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0 text-hud-amber" />
                  <span>{list.storage_warning}</span>
                </div>
              )}
            </>
          )}
        </div>
      </section>
    </div>
  );
}
