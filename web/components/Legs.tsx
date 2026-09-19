"use client";

import { useEffect, useState } from "react";
import { loadHistory, type History, type Leg } from "@/lib/data";
import { CHAIN, USDC, explorerTx } from "@/lib/config";
import { addr, ago } from "@/lib/format";

/**
 * Every leg the contract has executed, from its own Executed events.
 *
 * The event carries tokenIn, tokenOut, amountIn, amountOut and the mandate
 * version. It does NOT carry distance-to-target, so distance is not shown here
 * and is not reconstructed: the only honest source for it is the agent's own
 * recorded cycle, which publishes the distance it measured at the time. Two
 * implementations of the same number eventually disagree, and the one on screen
 * would then be the lie.
 */
export function Legs() {
  const [h, setH] = useState<History | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    loadHistory().then((v) => {
      setH(v);
      setLoaded(true);
    });
  }, []);

  if (!loaded) return null;

  const legs = h?.legs ?? [];

  return (
    <section style={{ marginTop: 64, paddingTop: 24, borderTop: "1px solid var(--bone-12)" }}>
      <div className="dim" style={{ fontSize: 12, letterSpacing: "0.08em", marginBottom: 14 }}>
        LEGS EXECUTED
      </div>

      {h && h.origin === "fork" && (
        <div
          style={{
            fontSize: 12,
            padding: "10px 12px",
            marginBottom: 18,
            border: "1px solid var(--bone-12)",
            maxWidth: 640,
          }}
        >
          <strong style={{ fontWeight: 500 }}>Fork run, not mainnet.</strong>{" "}
          <span className="dim">
            These swaps went through the real OKX router against real pool state
            on a fork of {CHAIN.name}. The amounts are what the router actually
            returned. The transaction hashes exist only on that fork, so they are
            shown but not linked — an explorer link here would be dead.
          </span>
        </div>
      )}

      {legs.length === 0 ? (
        <p className="dim" style={{ fontSize: 13, maxWidth: 640 }}>
          No legs recorded yet. This list is built from the contract&apos;s{" "}
          <span className="mono">Executed</span> events; until one is emitted
          there is nothing to show, and nothing is shown.
        </p>
      ) : (
        <>
          <div className="dim" style={{ fontSize: 12, marginBottom: 10 }}>
            {legs.length} leg{legs.length === 1 ? "" : "s"}, oldest first
          </div>
          {legs.map((l) => (
            <LegRow key={l.txHash + l.blockNumber} leg={l} linkable={h?.origin === "mainnet"} />
          ))}
        </>
      )}

      <Amendments h={h} />
    </section>
  );
}

/**
 * Target changes, from TargetsSet.
 *
 * Amending targets is permitted, so the guard against it is that it can never
 * happen quietly: the event carries both the old and the new targets, and the
 * version increments. A gap that closed because the target moved toward the
 * holding looks identical to one closed by trading, unless this is on screen.
 */
function Amendments({ h }: { h: History | null }) {
  const rows = h?.amendments ?? [];
  if (rows.length === 0) return null;

  return (
    <div style={{ marginTop: 32 }}>
      <div className="dim" style={{ fontSize: 12, letterSpacing: "0.08em", marginBottom: 6 }}>
        TARGETS AMENDED
      </div>
      <p className="dim" style={{ fontSize: 13, margin: "0 0 12px", maxWidth: 640 }}>
        Changing a target changes the distance without a single trade. Each
        change is recorded with the targets before and after it, so a gap that
        closed because the target moved cannot be mistaken for one closed by
        rebalancing.
      </p>
      {rows.map((a) => (
        <div key={a.txHash} style={{ padding: "12px 0", borderTop: "1px solid var(--bone-12)" }}>
          <div style={{ display: "flex", justifyContent: "space-between", gap: 16, flexWrap: "wrap" }}>
            <span style={{ fontSize: 13 }}>
              mandate {a.id} · version {a.version - 1} → {a.version}
            </span>
            <span className="faint" style={{ fontSize: 12 }}>{ago(a.timestamp)}</span>
          </div>
          {a.current.map((cur, i) => {
            const prev = a.previous[i] ?? "0";
            const changed = prev !== cur;
            return (
              <div key={i} className={changed ? "" : "faint"} style={{ fontSize: 12, marginTop: 4 }}>
                <span className="mono">{shares18(prev)}</span>
                {" → "}
                <span className="mono">{shares18(cur)}</span>
                {!changed && <span className="faint"> unchanged</span>}
              </div>
            );
          })}
        </div>
      ))}
    </div>
  );
}

/** Targets are held in shares, which are 18dp on every xStock tested. */
function shares18(raw: string): string {
  const s = raw.padStart(19, "0");
  return `${s.slice(0, -18).replace(/^0+(?=\d)/, "")}.${s.slice(-18).slice(0, 4)}`;
}

/** USDC is the only 6dp token in the set; everything else is 18dp. */
function amount(raw: string, token: string): string {
  const isUsdc = token.toLowerCase() === USDC.toLowerCase();
  const dp = isUsdc ? 6 : 18;
  const s = raw.padStart(dp + 1, "0");
  const whole = s.slice(0, -dp).replace(/^0+(?=\d)/, "");
  const frac = s.slice(-dp).slice(0, isUsdc ? 2 : 4);
  return `${whole}.${frac}`;
}

function LegRow({ leg, linkable }: { leg: Leg; linkable: boolean }) {
  const sold = leg.tokenIn.toLowerCase() !== USDC.toLowerCase();

  return (
    <div style={{ padding: "12px 0", borderTop: "1px solid var(--bone-12)" }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 16, flexWrap: "wrap" }}>
        <span style={{ fontSize: 13 }}>
          {sold ? "Sold" : "Bought"}{" "}
          <span className="mono">{amount(leg.amountIn, leg.tokenIn)}</span>{" "}
          <span className="dim">{addr(leg.tokenIn)}</span>
          {" → "}
          <span className="mono">{amount(leg.amountOut, leg.tokenOut)}</span>{" "}
          <span className="dim">{addr(leg.tokenOut)}</span>
        </span>
        <span className="faint" style={{ fontSize: 12 }}>
          {leg.timestamp ? ago(leg.timestamp) : `block ${leg.blockNumber}`}
        </span>
      </div>
      <div className="faint" style={{ fontSize: 12, marginTop: 4, wordBreak: "break-all" }}>
        mandate {leg.id} · version {leg.version} · block {leg.blockNumber} ·{" "}
        {linkable ? (
          <a className="mono" href={explorerTx(leg.txHash)} target="_blank" rel="noreferrer">
            {leg.txHash}
          </a>
        ) : (
          <span className="mono">{leg.txHash}</span>
        )}
      </div>
    </div>
  );
}
