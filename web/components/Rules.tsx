"use client";

import { bps, usdc } from "@/lib/format";

export type MandateView = {
  owner: `0x${string}`;
  agent: `0x${string}`;
  expiry: bigint;
  paused: boolean;
  revoked: boolean;
  driftBps: number;
  maxLegUsdc: bigint;
  totalCapUsdc: bigint;
  spentUsdc: bigint;
  version: bigint;
};

/**
 * The four limits as FOUR things, in two units. Conflating them is how a user
 * ends up believing the dollar cap bounds a sell. It does not — only the rate
 * limit does, and it is the only one expressed in shares.
 */
export function Rules({ m, rateBps }: { m: MandateView; rateBps: number | null }) {
  const spent = Number(m.spentUsdc) / 1e6;
  const cap = Number(m.totalCapUsdc) / 1e6;
  const pct = cap > 0 ? Math.min(100, (spent / cap) * 100) : 0;

  return (
    <section style={{ marginBottom: 48 }}>
      <div className="dim" style={{ fontSize: 12, letterSpacing: "0.08em", marginBottom: 16 }}>
        WHAT THE AGENT MAY DO — AS THE CONTRACT HOLDS IT
      </div>

      <div style={{ border: "1px solid var(--bone-12)", padding: 18, marginBottom: 18 }}>
        <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 8, gap: 12 }}>
          <span style={{ fontSize: 14 }}>Total that may ever be spent</span>
          <span className="mono">${usdc(m.spentUsdc)} / ${usdc(m.totalCapUsdc)}</span>
        </div>
        <div className="bar-track">
          <div className="bar-fill" style={{ width: `${pct}%` }} />
        </div>
        <p className="dim" style={{ fontSize: 13, margin: "12px 0 0" }}>
          <strong style={{ color: "var(--bone)" }}>
            The cap is not a budget, it is the loss bound.
          </strong>{" "}
          If the agent key were fully compromised and the router hostile, this is
          the most that can be lost. Selling does not give it more to spend.
        </p>
      </div>

      <Limit
        label="Maximum in a single purchase"
        value={`$${usdc(m.maxLegUsdc)}`}
        note="Bounds one buy. It does not bound a sell — sizing a sell in dollars would need a price the contract does not have."
      />
      <Limit
        label="Maximum movement per leg"
        value={rateBps === null ? "—" : bps(rateBps)}
        note="Of that token's target, in shares, in either direction. This is the only limit that bounds a sell, and it is why one oversized leg cannot empty a position."
      />
      <Limit
        label="Drift tolerance"
        value={bps(m.driftBps)}
        note="Below this, the agent does nothing. Convergence is terminal: a position at target is closed to the agent in both directions."
      />
      <Limit
        label="Expiry"
        value={new Date(Number(m.expiry) * 1000).toISOString().slice(0, 16).replace("T", " ") + "Z"}
        note="After this the mandate cannot execute again by any path. Holdings are untouched and remain the owner's."
      />
    </section>
  );
}

function Limit({ label, value, note }: { label: string; value: string; note: string }) {
  return (
    <div style={{ padding: "14px 0", borderTop: "1px solid var(--bone-12)" }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
        <span style={{ fontSize: 14 }}>{label}</span>
        <span className="mono">{value}</span>
      </div>
      <p className="dim" style={{ fontSize: 12, margin: "6px 0 0", maxWidth: 620 }}>{note}</p>
    </div>
  );
}
