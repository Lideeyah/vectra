"use client";

import type { AgentCycle } from "@/lib/data";
import { ago, elapsed } from "@/lib/format";

/**
 * The refusal log, given equal weight to the legs. Every cycle the agent either
 * acts or declines, and the refusal names the actual binding constraint rather
 * than the first blocker it hit. A product that shows its own inaction, with
 * reasons, is making a claim no screenshot can fake.
 */
export function Refusals({ cycle, stale }: { cycle: AgentCycle | null; stale: boolean }) {
  return (
    <section data-testid="refusals" style={{ marginBottom: 48 }}>
      <div
        className="dim"
        style={{
          fontSize: 12,
          letterSpacing: "0.08em",
          marginBottom: 12,
          display: "flex",
          justifyContent: "space-between",
          gap: 12,
        }}
      >
        <span>WHAT THE AGENT DID, AND DECLINED TO DO</span>
        {cycle && <span className="mono">{ago(cycle.ts)}</span>}
      </div>

      {!cycle && (
        <p className="dim" style={{ fontSize: 14, margin: 0 }}>
          No cycle has been published yet. Nothing is inferred in its place.
        </p>
      )}

      {cycle && stale && (
        <div
          style={{
            border: "1px solid var(--red)",
            padding: "12px 14px",
            marginBottom: 16,
            color: "var(--red)",
            fontSize: 13,
          }}
        >
          <strong>The agent has stopped.</strong>{" "}
          <span className="mono">{elapsed(cycle.ts)}</span> since the last cycle. A
          position that is not moving because nothing is running looks identical
          to one that is stable, so this is stated rather than left to inference.
        </div>
      )}

      {cycle && (
        <>
          {cycle.leg ? (
            <div data-testid="agent-leg" style={{ borderLeft: "2px solid var(--cyan)", paddingLeft: 14, marginBottom: 18 }}>
              <div className="mono cyan" style={{ fontSize: 14 }}>
                {cycle.leg.direction.toUpperCase()} {cycle.leg.symbol} · $
                {cycle.leg.amountUsd.toFixed(2)}
              </div>
              <div className="dim" style={{ fontSize: 13, marginTop: 4 }}>
                {cycle.leg.reason}
              </div>
              {cycle.leg.rejected?.length ? (
                <div className="faint mono" style={{ fontSize: 12, marginTop: 6 }}>
                  rejected:{" "}
                  {cycle.leg.rejected
                    .map((r) => `${r.direction} ${r.symbol} → ${r.distanceAfter}bps`)
                    .join("  ·  ")}
                </div>
              ) : null}
            </div>
          ) : (
            <div style={{ borderLeft: "2px solid var(--orange)", paddingLeft: 14, marginBottom: 18 }}>
              <div className="mono orange" style={{ fontSize: 14 }}>NO ACTION</div>
              <div className="dim" style={{ fontSize: 13, marginTop: 4 }}>
                {cycle.noActionReason ?? "no reason recorded"}
              </div>
            </div>
          )}

          {cycle.refusals.map((r, i) => (
            <div
              key={i}
              data-testid="refusal-row"
              data-token={r.token}
              style={{
                display: "flex",
                gap: 12,
                padding: "10px 0",
                borderTop: "1px solid var(--bone-12)",
                fontSize: 13,
              }}
            >
              <span className="mono faint" style={{ minWidth: 68 }}>
                {r.standing ? "STANDING" : r.token === "*" ? "ALL" : r.token}
              </span>
              <span className="dim">{r.reason}</span>
            </div>
          ))}
        </>
      )}
    </section>
  );
}
