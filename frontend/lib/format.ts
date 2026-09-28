export function money(n: number): string {
  // The sign goes before the currency ("-$12", not "$-12"), and a loss is
  // abbreviated the same way a gain is. Anything that rounds to zero is $0.
  if (n < 0) return -n >= 0.5 ? `-${money(-n)}` : "$0";
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `$${(n / 1_000).toFixed(1)}K`;
  return `$${n.toFixed(0)}`;
}

export function compact(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return `${n}`;
}

export function timeAgo(iso: string | null): string {
  if (!iso) return "—";
  const secs = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (secs < 60) return `${Math.floor(secs)}s ago`;
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
  if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`;
  return `${Math.floor(secs / 86400)}d ago`;
}

export const SEVERITY_COLOR: Record<string, string> = {
  info: "text-hud-cyan",
  success: "text-hud-emerald",
  warn: "text-hud-amber",
  critical: "text-hud-rose",
};
