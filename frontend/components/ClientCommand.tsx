"use client";

/**
 * ClientCommand — the agency side of Titan, inside the command centre.
 *
 * Until now /portal and /clients were standalone HTML pages living outside the
 * dashboard. That worked but made Titan feel like three products. This folds
 * client management into the same shell as Universe, Mission and War Room, so
 * managing a paying business is a first-class view rather than a side door.
 *
 * Everything here reads /api/admin/*, which stays behind the founder token.
 */

import { useCallback, useEffect, useState } from "react";
import { motion } from "framer-motion";
import {
  AlertTriangle, Building2, Euro, FileText, Loader2, Plus,
  RefreshCw, Search, ShieldAlert, Trash2, TrendingUp,
} from "lucide-react";

type Metrics = {
  seo_audits: number; posts_drafted: number; posts_approved: number;
  issues_found: number; issues_fixed: number;
};

type Client = {
  id: string; business_name: string; industry?: string; website?: string;
  instagram?: string; status: string; trial_days_left: number;
  last_login?: number | null; metrics: Metrics;
};

type Overview = {
  total: number; active: number; expired: number;
  expiring_soon: { id: string; business_name: string; days_left: number }[];
  totals: Metrics; clients: Client[];
};

type Opportunity = {
  id: string; offer: string; affected: number; clients: string[];
  unit_price_eur: number; total_eur: number; effort: string;
  pitch: string; urgent: boolean; evidence: string;
};

type Risk = { id: string; severity: string; title: string; detail: string; action: string };

type Discovery = {
  opportunities: Opportunity[]; risks: Risk[];
  pipeline_value_eur: number; urgent_value_eur: number;
};

const SEV: Record<string, string> = {
  critical: "text-rose-400 border-rose-500/40 bg-rose-500/5",
  high: "text-amber-400 border-amber-500/40 bg-amber-500/5",
  medium: "text-sky-400 border-sky-500/40 bg-sky-500/5",
  low: "text-slate-400 border-slate-600/40 bg-slate-500/5",
};

function token(): string {
  if (typeof window === "undefined") return "";
  return (
    localStorage.getItem("titan_token") ||
    sessionStorage.getItem("titan_token") ||
    ""
  );
}

async function api(path: string, init: RequestInit = {}) {
  return fetch(`/api${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token()}`,
      ...(init.headers || {}),
    },
    cache: "no-store",
  });
}

export default function ClientCommand() {
  const [ov, setOv] = useState<Overview | null>(null);
  const [disc, setDisc] = useState<Discovery | null>(null);
  const [busy, setBusy] = useState<string>("");
  const [adding, setAdding] = useState(false);
  const [err, setErr] = useState("");
  const [form, setForm] = useState({
    business_name: "", username: "", password: "", website: "",
    instagram: "", industry: "Restaurant", city: "", country: "Germany",
    logo_url: "", trial_days: 60,
  });

  const load = useCallback(async () => {
    try {
      const [a, b] = await Promise.all([
        api("/admin/clients"),
        api("/admin/discovery"),
      ]);
      if (a.ok) setOv(await a.json());
      if (b.ok) setDisc(await b.json());
    } catch {
      /* dashboard polls again shortly */
    }
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 30_000);
    return () => clearInterval(t);
  }, [load]);

  const runAudit = async (id: string) => {
    setBusy(id);
    try {
      await api(`/admin/clients/${id}/seo`, { method: "POST" });
      await load();
    } finally {
      setBusy("");
    }
  };

  const extend = async (id: string) => {
    setBusy(id);
    try {
      await api(`/admin/clients/${id}/extend?days=30`, { method: "POST" });
      await load();
    } finally {
      setBusy("");
    }
  };

  const remove = async (c: Client) => {
    if (!confirm(`Delete ${c.business_name}? Their login and history go permanently.`))
      return;
    setBusy(c.id);
    try {
      await api(`/admin/clients/${c.id}`, { method: "DELETE" });
      await load();
    } finally {
      setBusy("");
    }
  };

  const create = async () => {
    setErr("");
    if (!form.business_name || !form.username || !form.password) {
      setErr("Business name, username and password are required.");
      return;
    }
    const r = await api("/admin/clients", {
      method: "POST",
      body: JSON.stringify(form),
    });
    if (!r.ok) {
      setErr((await r.json()).detail || "Could not create client.");
      return;
    }
    setForm({ ...form, business_name: "", username: "", password: "", website: "", instagram: "" });
    setAdding(false);
    load();
  };

  const kpi = (label: string, value: string | number, tone = "text-hud-amber") => (
    <div className="rounded-xl border border-white/10 bg-black/30 px-4 py-3">
      <div className={`text-2xl font-semibold leading-none ${tone}`}>{value}</div>
      <div className="mt-1 text-[10px] uppercase tracking-widest text-slate-500">{label}</div>
    </div>
  );

  return (
    <div className="space-y-4">
      {/* header */}
      <div className="flex items-center justify-between">
        <div>
          <div className="flex items-center gap-2 text-sm font-semibold tracking-widest text-white">
            <Building2 className="h-4 w-4 text-hud-amber" /> CLIENT COMMAND
          </div>
          <div className="mt-1 text-[11px] text-slate-500">
            Every business you manage · SEO, compliance and content
          </div>
        </div>
        <div className="flex gap-2">
          <button
            onClick={load}
            className="flex items-center gap-1 rounded-lg border border-white/10 px-3 py-1.5 text-[11px] text-slate-300 transition hover:border-hud-amber/50 hover:text-hud-amber"
          >
            <RefreshCw className="h-3 w-3" /> Refresh
          </button>
          <button
            onClick={() => setAdding((v) => !v)}
            className="flex items-center gap-1 rounded-lg border border-emerald-500/40 px-3 py-1.5 text-[11px] text-emerald-300 transition hover:bg-emerald-500/10"
          >
            <Plus className="h-3 w-3" /> Onboard
          </button>
        </div>
      </div>

      {/* KPIs */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-6">
        {kpi("Clients", ov?.total ?? 0)}
        {kpi("Active", ov?.active ?? 0, "text-emerald-400")}
        {kpi("Expired", ov?.expired ?? 0, "text-rose-400")}
        {kpi("Audits", ov?.totals.seo_audits ?? 0, "text-sky-400")}
        {kpi("Issues found", ov?.totals.issues_found ?? 0, "text-violet-400")}
        {kpi(
          "Pipeline",
          disc ? `€${disc.pipeline_value_eur.toLocaleString()}` : "€0",
          "text-hud-amber",
        )}
      </div>

      {/* expiring trials */}
      {ov?.expiring_soon?.length ? (
        <div className="flex items-start gap-2 rounded-xl border border-amber-500/40 bg-amber-500/5 px-4 py-3 text-[12px] text-amber-300">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <div>
            <b>Trials ending soon:</b>{" "}
            {ov.expiring_soon
              .map((e) => `${e.business_name} (${e.days_left}d)`)
              .join(" · ")}
            . Convert or extend before they lapse.
          </div>
        </div>
      ) : null}

      {/* onboarding */}
      {adding && (
        <motion.div
          initial={{ opacity: 0, height: 0 }}
          animate={{ opacity: 1, height: "auto" }}
          className="overflow-hidden rounded-xl border border-white/10 bg-black/30 p-4"
        >
          <div className="mb-3 text-[10px] uppercase tracking-widest text-slate-500">
            Onboard a business
          </div>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
            {([
              ["business_name", "Business name"],
              ["industry", "Industry"],
              ["website", "Website"],
              ["city", "City"],
              ["instagram", "Instagram handle"],
              ["logo_url", "Logo URL"],
              ["username", "Login username"],
              ["password", "Login password"],
            ] as const).map(([k, label]) => (
              <label key={k} className="block">
                <span className="mb-1 block text-[9px] uppercase tracking-widest text-slate-500">
                  {label}
                </span>
                <input
                  type={k === "password" ? "password" : "text"}
                  value={(form as never)[k] as string}
                  onChange={(e) => setForm({ ...form, [k]: e.target.value })}
                  className="w-full rounded-lg border border-white/10 bg-black/40 px-3 py-2 text-[12px] text-slate-200 outline-none focus:border-hud-amber/60"
                />
              </label>
            ))}
            <label className="block">
              <span className="mb-1 block text-[9px] uppercase tracking-widest text-slate-500">
                Country — sets the legal rules checked
              </span>
              <select
                value={form.country}
                onChange={(e) => setForm({ ...form, country: e.target.value })}
                className="w-full rounded-lg border border-white/10 bg-black/40 px-3 py-2 text-[12px] text-slate-200 outline-none focus:border-hud-amber/60"
              >
                {["Germany","Austria","Switzerland","France","Italy","Spain",
                  "Netherlands","United Kingdom","United States","Pakistan"].map((c) => (
                  <option key={c}>{c}</option>
                ))}
              </select>
            </label>
          </div>
          {err && <div className="mt-2 text-[11px] text-rose-400">{err}</div>}
          <button
            onClick={create}
            className="mt-3 rounded-lg border border-emerald-500/40 px-4 py-2 text-[11px] text-emerald-300 transition hover:bg-emerald-500/10"
          >
            Create client
          </button>
        </motion.div>
      )}

      {/* clients */}
      <div className="rounded-xl border border-white/10 bg-black/30 p-4">
        <div className="mb-3 text-[10px] uppercase tracking-widest text-slate-500">
          Clients
        </div>
        {!ov?.clients.length ? (
          <div className="py-8 text-center text-[12px] text-slate-500">
            No clients yet. Use Onboard to add the first.
          </div>
        ) : (
          <div className="space-y-2">
            {ov.clients.map((c) => (
              <div
                key={c.id}
                className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-white/5 bg-black/20 px-3 py-3 transition hover:border-hud-amber/30"
              >
                <div className="min-w-[200px] flex-1">
                  <div className="text-[13px] text-white">{c.business_name}</div>
                  <div className="mt-0.5 text-[10px] text-slate-500">
                    {c.industry}
                    {c.website ? ` · ${c.website.replace(/^https?:\/\//, "")}` : " · no website"}
                    {c.instagram ? ` · @${c.instagram}` : ""}
                  </div>
                </div>
                <div className="text-center">
                  <div
                    className={`text-lg leading-none ${
                      c.trial_days_left <= 0
                        ? "text-rose-400"
                        : c.trial_days_left <= 14
                        ? "text-amber-400"
                        : "text-emerald-400"
                    }`}
                  >
                    {c.trial_days_left}
                  </div>
                  <div className="text-[9px] uppercase tracking-wider text-slate-600">
                    days left
                  </div>
                </div>
                <div className="text-[10px] text-slate-500">
                  {c.metrics.seo_audits} audits
                  <br />
                  {c.metrics.issues_found} issues
                </div>
                <div className="flex flex-wrap gap-1.5">
                  <button
                    disabled={busy === c.id}
                    onClick={() => runAudit(c.id)}
                    className="flex items-center gap-1 rounded-md border border-white/10 px-2.5 py-1 text-[10px] text-slate-300 transition hover:border-sky-400/50 hover:text-sky-300 disabled:opacity-40"
                  >
                    {busy === c.id ? (
                      <Loader2 className="h-3 w-3 animate-spin" />
                    ) : (
                      <Search className="h-3 w-3" />
                    )}
                    Audit
                  </button>
                  <a
                    href={`/api/admin/clients/${c.id}/report.pdf`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-1 rounded-md border border-white/10 px-2.5 py-1 text-[10px] text-slate-300 transition hover:border-hud-amber/50 hover:text-hud-amber"
                  >
                    <FileText className="h-3 w-3" /> PDF
                  </a>
                  <button
                    disabled={busy === c.id}
                    onClick={() => extend(c.id)}
                    className="rounded-md border border-white/10 px-2.5 py-1 text-[10px] text-slate-300 transition hover:border-emerald-400/50 hover:text-emerald-300 disabled:opacity-40"
                  >
                    +30d
                  </button>
                  <button
                    disabled={busy === c.id}
                    onClick={() => remove(c)}
                    className="rounded-md border border-rose-500/30 px-2.5 py-1 text-[10px] text-rose-400 transition hover:bg-rose-500/10 disabled:opacity-40"
                  >
                    <Trash2 className="h-3 w-3" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* discovery */}
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        <div className="rounded-xl border border-white/10 bg-black/30 p-4">
          <div className="mb-3 flex items-center gap-2 text-[10px] uppercase tracking-widest text-slate-500">
            <TrendingUp className="h-3.5 w-3.5 text-emerald-400" /> Sellable work found
          </div>
          {!disc?.opportunities.length ? (
            <div className="py-6 text-center text-[11px] text-slate-500">
              Run audits to surface recurring work worth selling.
            </div>
          ) : (
            <div className="space-y-2">
              {disc.opportunities.slice(0, 6).map((o) => (
                <div key={o.id} className="rounded-lg border border-white/5 bg-black/20 px-3 py-2.5">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-[12px] text-white">
                      {o.offer}
                      {o.urgent && (
                        <span className="ml-2 rounded-full bg-rose-500/15 px-2 py-0.5 text-[9px] uppercase tracking-wider text-rose-400">
                          urgent
                        </span>
                      )}
                    </span>
                    <span className="flex items-center gap-0.5 text-[13px] text-emerald-400">
                      <Euro className="h-3 w-3" />
                      {o.total_eur.toLocaleString()}
                    </span>
                  </div>
                  <div className="mt-1 text-[10px] text-slate-500">
                    {o.evidence} · {o.effort}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="rounded-xl border border-white/10 bg-black/30 p-4">
          <div className="mb-3 flex items-center gap-2 text-[10px] uppercase tracking-widest text-slate-500">
            <ShieldAlert className="h-3.5 w-3.5 text-amber-400" /> Portfolio risks
          </div>
          {!disc?.risks.length ? (
            <div className="py-6 text-center text-[11px] text-slate-500">
              Nothing at risk.
            </div>
          ) : (
            <div className="space-y-2">
              {disc.risks.map((r) => (
                <div
                  key={r.id}
                  className={`rounded-lg border px-3 py-2.5 ${SEV[r.severity] || SEV.low}`}
                >
                  <div className="text-[12px]">{r.title}</div>
                  <div className="mt-1 text-[10px] text-slate-400">{r.detail}</div>
                  <div className="mt-1 text-[10px] italic text-slate-500">{r.action}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
