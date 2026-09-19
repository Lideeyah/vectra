"use client";

import { shares } from "@/lib/format";

export type Row = {
  symbol: string;
  address: string;
  current: bigint;
  target: bigint;
};

/**
 * The hero: distance from target, not value. Target is a hairline outline,
 * actual is a solid fill, and the offset between them carries the information —
 * DESIGN.md section 1. Drift is read by looking before any number is read.
 */
export function Convergence({
  rows,
  toleranceBps,
}: {
  rows: Row[];
  toleranceBps: number;
}) {
  const totalGapBps = rows.reduce((acc, r) => {
    if (r.target === 0n) return acc;
    const gap = r.current > r.target ? r.current - r.target : r.target - r.current;
    return acc + Number((gap * 10000n) / r.target);
  }, 0);

  const within = rows.every((r) => {
    if (r.target === 0n) return true;
    const gap = r.current > r.target ? r.current - r.target : r.target - r.current;
    return Number((gap * 10000n) / r.target) <= toleranceBps;
  });

  return (
    <section style={{ marginBottom: 48 }}>
      <div className="dim" style={{ fontSize: 12, letterSpacing: "0.08em", marginBottom: 12 }}>
        TOTAL DISTANCE FROM TARGET
      </div>

      <div style={{ display: "flex", alignItems: "baseline", gap: 16, flexWrap: "wrap" }}>
        <div
          className="mono"
          style={{
            fontSize: "clamp(48px, 12vw, 96px)",
            lineHeight: 1,
            color: within ? "var(--cyan)" : "var(--orange)",
          }}
        >
          {(totalGapBps / 100).toFixed(2)}
          <span style={{ fontSize: "0.35em", marginLeft: 6 }}>%</span>
        </div>
        <div className="dim" style={{ fontSize: 13, maxWidth: 280 }}>
          {within
            ? `within the ${(toleranceBps / 100).toFixed(2)}% tolerance — the agent will not act`
            : `beyond the ${(toleranceBps / 100).toFixed(2)}% tolerance — a leg is warranted`}
        </div>
      </div>

      <hr className="rule" style={{ margin: "32px 0 0" }} />

      {rows.map((r) => {
        const over = r.current > r.target;
        const pct =
          r.target === 0n ? 0 : Math.min(200, Number((r.current * 10000n) / r.target) / 100);
        const gap = over ? r.current - r.target : r.target - r.current;
        return (
          <div key={r.address} style={{ padding: "18px 0", borderBottom: "1px solid var(--bone-12)" }}>
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 10, gap: 12 }}>
              <span className="mono" style={{ fontSize: 15 }}>{r.symbol}</span>
              <span className="mono dim" style={{ fontSize: 13 }}>
                {over ? "SELL" : gap === 0n ? "AT TARGET" : "BUY"}
              </span>
            </div>

            <div className="bar-track">
              <div
                className={`bar-fill${over ? " over" : ""}`}
                style={{ width: `${Math.min(100, pct)}%` }}
              />
            </div>

            <div
              className="mono"
              style={{
                display: "flex",
                justifyContent: "space-between",
                marginTop: 8,
                fontSize: 12,
                color: "var(--bone-60)",
                gap: 12,
                flexWrap: "wrap",
              }}
            >
              <span>actual {shares(r.current)}</span>
              <span>target {shares(r.target)}</span>
              <span style={{ color: over ? "var(--orange)" : "var(--bone-60)" }}>
                gap {over ? "+" : "−"}{shares(gap)}
              </span>
            </div>
          </div>
        );
      })}
    </section>
  );
}
