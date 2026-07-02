"use client";

import { useCallback, useEffect, useState } from "react";
import {
  BriefcaseBusiness,
  CheckCircle2,
  Copy,
  ExternalLink,
  FileText,
  RefreshCw,
} from "lucide-react";
import { api } from "@/lib/api";
import type { JobItem, JobsState } from "@/lib/types";

// Job Radar page: live-found remote jobs/gigs, fit scores, tailored proposals.
// Compliant by design — Titan finds + drafts, Abdullah clicks apply.
export function JobRadar() {
  const [state, setState] = useState<JobsState | null>(null);
  const [query, setQuery] = useState("");
  const [scanning, setScanning] = useState(false);
  const [proposals, setProposals] = useState<Record<string, string>>({});
  const [busyId, setBusyId] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setState(await api.jobs());
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const scan = async () => {
    if (scanning) return;
    setScanning(true);
    try {
      const res = await api.jobsScan(query);
      if (res) setState(res);
    } finally {
      setScanning(false);
    }
  };

  const draft = async (job: JobItem) => {
    if (busyId) return;
    setBusyId(job.id);
    try {
      const res = await api.jobProposal(job.title, job.url, job.why);
      if (res) setProposals((p) => ({ ...p, [job.id]: res.proposal }));
    } finally {
      setBusyId(null);
    }
  };

  const toggleApplied = async (job: JobItem) => {
    const updated = await api.jobApplied(job.id);
    if (updated && state) {
      setState({
        ...state,
        items: state.items.map((it) => (it.id === job.id ? { ...it, applied: updated.applied } : it)),
      });
    }
  };

  const items = state?.items ?? [];
  const appliedCount = items.filter((i) => i.applied).length;

  return (
    <div className="space-y-4">
      <section className="panel">
        <header className="panel-header">
          <div className="flex items-center gap-2">
            <BriefcaseBusiness className="h-4 w-4 text-hud-emerald" strokeWidth={1.6} />
            <h2 className="text-sm font-medium text-slate-200">Job Radar</h2>
            <span className="hud-label">finds + drafts · you click apply</span>
          </div>
          <span className="text-[10px] text-slate-500">
            {items.length} found · {appliedCount} applied
            {state?.last_scan ? ` · last scan ${new Date(state.last_scan).toLocaleTimeString()}` : ""}
          </span>
        </header>

        <div className="space-y-3 p-3">
          <div className="flex items-center gap-2">
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && void scan()}
              placeholder="What to hunt (blank = remote AI/full-stack gigs)"
              className="flex-1 rounded-lg border border-edge bg-panel-2/60 px-2.5 py-1.5 text-xs text-slate-200 placeholder:text-slate-600 focus:border-hud-emerald/40 focus:outline-none"
            />
            <button
              onClick={() => void scan()}
              disabled={scanning}
              className="flex items-center gap-1.5 rounded-lg border border-hud-emerald/40 bg-hud-emerald/10 px-3 py-1.5 text-xs text-hud-emerald hover:bg-hud-emerald/20 disabled:opacity-50"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${scanning ? "animate-spin" : ""}`} />
              {scanning ? "Hunting…" : "Hunt jobs"}
            </button>
          </div>

          {items.length === 0 && (
            <div className="py-6 text-center text-[11px] text-slate-600">
              {state?.live === false && state?.last_scan
                ? "No live results — make sure TAVILY_API_KEY is set, then hunt again."
                : "Hit Hunt jobs to find live openings matched to your real skills."}
            </div>
          )}

          <div className="space-y-2">
            {items.map((job) => (
              <div key={job.id} className={`rounded-lg border p-3 ${job.applied ? "border-hud-emerald/40 bg-hud-emerald/5" : "border-edge/60 bg-panel-2/40"}`}>
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <a href={job.url} target="_blank" rel="noreferrer" className="flex items-center gap-1.5 text-xs font-medium text-slate-200 hover:text-hud-cyan">
                      <span className="truncate">{job.title}</span>
                      <ExternalLink className="h-3 w-3 shrink-0" />
                    </a>
                    <p className="mt-1 text-[11px] text-slate-400">{job.why}</p>
                  </div>
                  <div className="flex shrink-0 flex-col items-end gap-1.5">
                    {job.score !== null && (
                      <span
                        className={`rounded px-1.5 py-0.5 font-mono text-[11px] ${
                          job.score >= 70
                            ? "bg-hud-emerald/15 text-hud-emerald"
                            : job.score >= 40
                              ? "bg-hud-amber/15 text-hud-amber"
                              : "bg-slate-700/40 text-slate-400"
                        }`}
                      >
                        fit {job.score}
                      </span>
                    )}
                  </div>
                </div>

                <div className="mt-2 flex flex-wrap items-center gap-2">
                  <button
                    onClick={() => void draft(job)}
                    disabled={busyId === job.id}
                    className="flex items-center gap-1 rounded border border-edge bg-panel/70 px-2 py-1 text-[10px] text-slate-300 hover:border-hud-cyan/40 hover:text-hud-cyan disabled:opacity-50"
                  >
                    <FileText className="h-3 w-3" />
                    {busyId === job.id ? "Drafting…" : proposals[job.id] ? "Redraft proposal" : "Draft proposal"}
                  </button>
                  <button
                    onClick={() => void toggleApplied(job)}
                    className={`flex items-center gap-1 rounded border px-2 py-1 text-[10px] ${
                      job.applied
                        ? "border-hud-emerald/40 text-hud-emerald"
                        : "border-edge text-slate-400 hover:text-slate-200"
                    }`}
                  >
                    <CheckCircle2 className="h-3 w-3" />
                    {job.applied ? "Applied ✓" : "Mark applied"}
                  </button>
                </div>

                {proposals[job.id] && (
                  <div className="mt-2 rounded-lg border border-hud-cyan/20 bg-hud-cyan/5 p-2.5">
                    <div className="mb-1 flex items-center justify-between">
                      <span className="text-[10px] font-semibold uppercase tracking-wide text-hud-cyan">Proposal draft</span>
                      <button
                        onClick={() => void navigator.clipboard.writeText(proposals[job.id])}
                        className="flex items-center gap-1 text-[10px] text-slate-400 hover:text-hud-cyan"
                      >
                        <Copy className="h-3 w-3" /> Copy
                      </button>
                    </div>
                    <p className="whitespace-pre-line text-[11px] leading-relaxed text-slate-300">{proposals[job.id]}</p>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      </section>
    </div>
  );
}
