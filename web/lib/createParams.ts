import type { Address } from "viem";
import type { CreateParams } from "./write";

/**
 * The form's values turned into contract arguments.
 *
 * Extracted from the component so it can be tested against a real chain: the
 * risk here is a units or encoding error between what the form shows and what
 * createMandate receives, and that class of bug is invisible to a rendering
 * check. It is the same class the units trace caught on the contract side.
 */
export type FormValues = {
  tokens: Address[];
  targetsDecimal: string[];   // as typed, e.g. "4.5"
  capUsd: string;
  legUsd: string;
  ratePct: string;
  driftPct: string;
  days: string;
  agent: Address;
  nowSeconds: number;
};

/** Decimal string to 18dp share units, without floating point anywhere. */
export function toShares(v: string): bigint {
  const clean = (v || "0").trim();
  const [w = "0", f = ""] = clean.split(".");
  return BigInt(w || "0") * 10n ** 18n + BigInt((f + "0".repeat(18)).slice(0, 18) || "0");
}

/** Decimal USD to 6dp USDC units, without floating point. */
export function toUsdc(v: string): bigint {
  const clean = (v || "0").trim();
  const [w = "0", f = ""] = clean.split(".");
  return BigInt(w || "0") * 10n ** 6n + BigInt((f + "000000").slice(0, 6) || "0");
}

/** Percent string to basis points. 20 -> 2000, 0.5 -> 50. */
export function toBps(v: string): number {
  const n = Number(v);
  if (!Number.isFinite(n)) throw new Error(`not a number: ${v}`);
  return Math.round(n * 100);
}

export function evenWeights(n: number): number[] {
  if (n < 1) throw new Error("empty basket");
  const base = Math.floor(10000 / n);
  const w = Array(n).fill(base);
  w[0] += 10000 - base * n;
  return w;
}

export function buildCreateParams(f: FormValues): CreateParams {
  if (f.tokens.length !== f.targetsDecimal.length) {
    throw new Error("tokens and targets are different lengths");
  }
  return {
    tokens: f.tokens,
    weightsBps: evenWeights(f.tokens.length),
    targetShares: f.targetsDecimal.map(toShares),
    driftBps: toBps(f.driftPct),
    maxLegUsdc: toUsdc(f.legUsd),
    totalCapUsdc: toUsdc(f.capUsd),
    maxLegBpsOfTarget: toBps(f.ratePct),
    expiry: BigInt(f.nowSeconds + Number(f.days) * 86400),
    agent: f.agent,
  };
}
