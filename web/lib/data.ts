import { DATA_BASE } from "./config";

/**
 * The recorder's and agent's committed output, fetched raw from the repository.
 * There is no database: these files ARE the record, and each carries the
 * timestamp of the observation so nothing on screen is undated.
 */

export type Constituent = {
  symbol: string;
  name?: string;
  address: string;
  decimals: number;
  priceImpactPctAtProbe: number | null;
  multiplierAtFix: number | null;
};

export type Constituents = {
  fixedAt: string;
  selectionBasis: string;
  xstocksOnChain: number;
  quotable: number;
  probeNotionalUsd: number;
  constituents: Constituent[];
};

export type Refusal = { token: string; reason: string };

export type AgentCycle = {
  ts: string;
  mode: string;
  owner: string;
  contract: string | null;
  totalUsd: number;
  usdcValueUsd: number;
  positions: {
    symbol: string;
    address: string;
    decimals: number;
    shares: number | null;
    multiplier: number | null;
    priceUsd: number | null;
    valueUsd: number | null;
    targetWeightBps: number;
    actualWeightBps: number;
    driftBps: number;
  }[];
  leg: {
    direction: string;
    symbol: string;
    amountUsd: number;
    reason: string;
    distanceBefore: number;
    distanceAfter: number;
    reductionBps: number;
    rejected?: { direction: string; symbol: string; distanceAfter: number }[];
  } | null;
  noActionReason: string | null;
  refusals: Refusal[];
};

async function getJSON<T>(path: string): Promise<T | null> {
  try {
    const r = await fetch(`${DATA_BASE}/${path}`, { cache: "no-store" });
    if (!r.ok) return null;
    return (await r.json()) as T;
  } catch {
    return null;
  }
}

/** The tradeable set, with its verification date. Never a hardcoded guess. */
export function loadConstituents() {
  return getJSON<Constituents>("constituents.json");
}

/**
 * The agent's own published decision. Deliberately NOT recomputed here: two
 * implementations of the same decision will eventually disagree, and the one on
 * screen would then be a lie.
 */
export function loadLatestCycle() {
  // A STABLE path, not a timestamped one: raw file hosting serves files rather
  // than directory listings, so a timestamped name is unreachable from a
  // browser without an index. The agent writes both — the timestamped file is
  // the archive, this is the readable head.
  return getJSON<AgentCycle>("agent/latest.json");
}

export type PriceRow = {
  ts_utc: string;
  bucket: string;
  status: string;
  symbol: string;
  price_usd: string;
  multiplier: string;
  routes: string;
};

/** The recorder's series, parsed from the committed CSV. */
export async function loadPrices(limit = 400): Promise<PriceRow[]> {
  try {
    const r = await fetch(`${DATA_BASE}/prices.csv`, { cache: "no-store" });
    if (!r.ok) return [];
    const text = await r.text();
    const lines = text.trim().split("\n");
    const head = lines[0].split(",");
    const idx = (k: string) => head.indexOf(k);
    return lines
      .slice(Math.max(1, lines.length - limit))
      .map((l) => {
        const c = l.split(",");
        return {
          ts_utc: c[idx("ts_utc")],
          bucket: c[idx("bucket")],
          status: c[idx("status")],
          symbol: c[idx("symbol")],
          price_usd: c[idx("price_usd")],
          multiplier: c[idx("multiplier")],
          routes: c[idx("routes")],
        };
      })
      .filter((r) => r.symbol);
  } catch {
    return [];
  }
}

/**
 * Executed and TargetsSet events, decoded by tools/decode_legs.py.
 *
 * `origin` is load-bearing: a fork run produces real swaps through the real
 * router, but its transaction hashes exist only on that fork. The interface
 * shows them as hashes and refuses to link them to the explorer, because a
 * dead link presented as proof is worse than no link.
 */
export type Leg = {
  id: string;
  tokenIn: string;
  tokenOut: string;
  amountIn: string;
  amountOut: string;
  version: number;
  txHash: string;
  blockNumber: number;
  timestamp: number | null;
};

export type Amendment = {
  id: string;
  previous: string[];
  current: string[];
  version: number;
  timestamp: number;
  txHash: string;
  blockNumber: number;
};

export type History = {
  origin: "fork" | "mainnet";
  chainId: number;
  note: string;
  legs: Leg[];
  amendments: Amendment[];
};

/**
 * Mainnet history if it exists, otherwise the fork run. Never merged: they are
 * different chains, and a combined list would attribute fork transactions to
 * X Layer.
 */
export async function loadHistory(): Promise<History | null> {
  return (
    (await getJSON<History>("history.json")) ??
    (await getJSON<History>("dev/history.json"))
  );
}
