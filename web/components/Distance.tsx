"use client";

import { useEffect, useState } from "react";
import { loadDistance, type DistanceRow } from "@/lib/data";
import { bps } from "@/lib/format";

/**
 * Distance from target over time — the one number this product is about,
 * plotted against the only thing that can prove it: its own recorded history.
 *
 * Two rules hold this together.
 *
 * A cycle the agent could not price records NA, and NA BREAKS THE LINE. It is
 * never interpolated across. A continuous line drawn through a period when
 * nothing was known is the most flattering possible lie: it shows the basket
 * holding steady precisely where there is no evidence it held anything.
 *
 * And the series is short because it is real. It starts when recording started
 * and cannot be backfilled, so an empty chart is the honest state of a product
 * that has not run long enough yet, not a rendering failure.
 */
export function Distance({ toleranceBps, mandateId }: { toleranceBps?: number; mandateId?: bigint }) {
  const [rows, setRows] = useState<DistanceRow[] | null>(null);

  useEffect(() => {
    loadDistance(600, mandateId).then(setRows);
    const t = setInterval(
      () => void loadDistance(600, mandateId).then(setRows), 120_000);
    return () => clearInterval(t);
  }, [mandateId]);

  if (rows === null) return null;

  // The SHARE-space metric — the one the hero shows. The weight-space number
  // is what the agent decides on and stays in the cycle log; plotting a
  // different number from the one displayed above it is how one word ends up
  // meaning two things.
  const measured = rows.filter((r) => r.shareDistanceBps !== null);
  // Two different reasons a row has no value, and they must not read alike.
  // A cycle that could not price anything was genuinely unmeasurable. A cycle
  // recorded before this column existed WAS measured — just not in this
  // metric — and calling it unmeasurable would be a false statement about the
  // agent's history.
  const predatesMetric = rows.filter(
    (r) => r.shareDistanceBps === null && r.status === "priced",
  ).length;
  const unmeasured = rows.length - measured.length - predatesMetric;

  return (
    <section data-testid="distance-chart" style={{ marginTop: 64, paddingTop: 24, borderTop: "1px solid var(--bone-12)" }}>
      <div className="dim" style={{ fontSize: 12, letterSpacing: "0.08em", marginBottom: 14 }}>
        DISTANCE FROM TARGET, OVER TIME
      </div>
      <p className="faint" style={{ fontSize: 12, margin: "0 0 12px", maxWidth: 560 }}>
        The same measure as the figure above: each holding&apos;s gap to its
        target, in shares, summed.
      </p>

      {measured.length < 2 ? (
        <p className="dim" style={{ fontSize: 13, maxWidth: 640 }}>
          {rows.length === 0 ? (
            <>
              No cycles recorded yet. This series is appended one row per agent
              cycle and cannot be backfilled, so it begins when the agent does.
            </>
          ) : (
            <>
              {rows.length} cycle{rows.length === 1 ? "" : "s"} recorded,{" "}
              {measured.length} carrying this measure.{" "}
              {predatesMetric > 0 && (
                <>
                  {predatesMetric} {predatesMetric === 1 ? "was" : "were"}{" "}
                  recorded before it was introduced and {predatesMetric === 1 ? "is" : "are"}{" "}
                  left blank rather than computed after the fact.{" "}
                </>
              )}
              {unmeasured > 0 && (
                <>
                  {unmeasured} could not price every position, and record no
                  distance at all rather than one computed from the part that
                  quoted.{" "}
                </>
              )}
              Not yet enough to plot.
            </>
          )}
        </p>
      ) : (
        <Plot rows={rows} measured={measured} toleranceBps={toleranceBps} />
      )}

      {rows.length > 0 && (
        <div className="faint" style={{ fontSize: 12, marginTop: 12 }}>
          {rows.length} cycle{rows.length === 1 ? "" : "s"} ·{" "}
          {measured.length} measured
          {predatesMetric > 0 && <> · {predatesMetric} predate this measure</>}
          {unmeasured > 0 && (
            <> · {unmeasured} unmeasurable, shown as breaks rather than joined up</>
          )}
          {" · "}from {rows[0].ts} to {rows[rows.length - 1].ts}
        </div>
      )}
    </section>
  );
}

const W = 720;
const H = 200;
const PAD = { l: 48, r: 12, t: 12, b: 22 };

function Plot({
  rows, measured, toleranceBps,
}: {
  rows: DistanceRow[];
  measured: DistanceRow[];
  toleranceBps?: number;
}) {
  const times = rows.map((r) => Date.parse(r.ts + "").valueOf());
  const t0 = Math.min(...times);
  const t1 = Math.max(...times);
  const span = Math.max(1, t1 - t0);

  const values = measured.map((r) => r.shareDistanceBps as number);
  // The tolerance line must be inside the frame, or a chart showing every
  // point above tolerance looks identical to one showing every point below it.
  const hi = Math.max(...values, toleranceBps ?? 0) * 1.1 || 1;

  const x = (ts: string) =>
    PAD.l + ((Date.parse(ts) - t0) / span) * (W - PAD.l - PAD.r);
  const y = (v: number) => PAD.t + (1 - v / hi) * (H - PAD.t - PAD.b);

  // Segments, split at every unmeasurable cycle. This is the whole point: the
  // line stops where the evidence stops.
  const segments: DistanceRow[][] = [];
  let run: DistanceRow[] = [];
  for (const r of rows) {
    if (r.shareDistanceBps === null) {
      if (run.length) segments.push(run);
      run = [];
    } else {
      run.push(r);
    }
  }
  if (run.length) segments.push(run);

  return (
    <div style={{ overflowX: "auto" }}>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H}
           role="img" aria-label="Distance from target over time">
        {/* tolerance */}
        {toleranceBps !== undefined && toleranceBps > 0 && (
          <>
            <line x1={PAD.l} x2={W - PAD.r} y1={y(toleranceBps)} y2={y(toleranceBps)}
                  stroke="var(--cyan)" strokeWidth="1" strokeDasharray="3 3" opacity="0.6" />
            <text x={W - PAD.r} y={y(toleranceBps) - 4} textAnchor="end"
                  fontSize="10" fill="var(--cyan)" opacity="0.8">
              tolerance {bps(toleranceBps)}
            </text>
          </>
        )}

        {/* axes */}
        <line x1={PAD.l} x2={PAD.l} y1={PAD.t} y2={H - PAD.b}
              stroke="currentColor" opacity="0.2" />
        <line x1={PAD.l} x2={W - PAD.r} y1={H - PAD.b} y2={H - PAD.b}
              stroke="currentColor" opacity="0.2" />
        <text x={PAD.l - 6} y={y(hi) + 4} textAnchor="end" fontSize="10"
              fill="currentColor" opacity="0.5">{bps(hi)}</text>
        <text x={PAD.l - 6} y={y(0) + 4} textAnchor="end" fontSize="10"
              fill="currentColor" opacity="0.5">0</text>

        {/* breaks: a visible gap, labelled, rather than a joined line */}
        {rows.map((r, i) =>
          r.shareDistanceBps === null ? (
            <line key={`gap-${i}`} x1={x(r.ts)} x2={x(r.ts)} y1={PAD.t} y2={H - PAD.b}
                  stroke="currentColor" strokeWidth="1" opacity="0.12" />
          ) : null,
        )}

        {segments.map((seg, i) => (
          <polyline
            key={`seg-${i}`}
            fill="none"
            stroke="var(--cyan)"
            strokeWidth="1.5"
            points={seg.map((r) => `${x(r.ts)},${y(r.shareDistanceBps as number)}`).join(" ")}
          />
        ))}

        {/* a cycle that executed a leg is marked, so movement can be read
            against the action that caused it rather than assumed */}
        {rows.map((r, i) =>
          r.shareDistanceBps !== null && r.legSymbol ? (
            <circle key={`leg-${i}`} cx={x(r.ts)} cy={y(r.shareDistanceBps)} r="3"
                    fill="var(--cyan)">
              <title>{`${r.legDirection} ${r.legSymbol} $${r.legUsd ?? "?"} — ${r.ts}`}</title>
            </circle>
          ) : null,
        )}

        {measured.length > 0 && (
          <circle cx={x(measured[measured.length - 1].ts)}
                  cy={y(measured[measured.length - 1].shareDistanceBps as number)}
                  r="2" fill="var(--cyan)" />
        )}
      </svg>
    </div>
  );
}
