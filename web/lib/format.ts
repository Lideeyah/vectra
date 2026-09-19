/** Shares are 18dp on every xStock tested. Formatting never invents precision. */
export function shares(v: bigint, dp = 4): string {
  const s = v.toString().padStart(19, "0");
  const whole = s.slice(0, -18).replace(/^0+(?=\d)/, "");
  const frac = s.slice(-18).slice(0, dp);
  return `${whole}.${frac}`;
}

export function usdc(v: bigint): string {
  const s = v.toString().padStart(7, "0");
  return `${s.slice(0, -6).replace(/^0+(?=\d)/, "")}.${s.slice(-6, -4)}`;
}

export function bps(v: number): string {
  return `${(v / 100).toFixed(2)}%`;
}

export function addr(a: string): string {
  return `${a.slice(0, 6)}…${a.slice(-4)}`;
}

export function ago(iso: string | number): string {
  const t = typeof iso === "number" ? iso * 1000 : Date.parse(iso);
  const s = Math.max(0, Math.floor((Date.now() - t) / 1000));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

/** Elapsed/remaining time, counting, in mono. Waiting is measured, not animated. */
export function elapsed(sinceIso: string | number): string {
  const t = typeof sinceIso === "number" ? sinceIso * 1000 : Date.parse(sinceIso);
  const s = Math.max(0, Math.floor((Date.now() - t) / 1000));
  const m = Math.floor(s / 60);
  const h = Math.floor(m / 60);
  if (h > 0) return `${h}h ${String(m % 60).padStart(2, "0")}m`;
  if (m > 0) return `${m}m ${String(s % 60).padStart(2, "0")}s`;
  return `${s}s`;
}
