/**
 * Everything address-shaped lives here, not scattered through components.
 * The contract may not be deployed yet; the predicted CREATE address is used
 * until it is, and the interface must render honestly either way.
 */
export const CHAIN = {
  id: 196,
  name: "X Layer",
  // Overridable so the interface can be pointed at a local anvil fork of X
  // Layer for development. The chain id stays 196 because the fork IS X Layer.
  rpc: process.env.NEXT_PUBLIC_RPC ?? "https://rpc.xlayer.tech",
  explorer: "https://www.oklink.com/x-layer",
  currency: { name: "OKB", symbol: "OKB", decimals: 18 },
} as const;

/** Predicted CREATE address (deployer 0x2F45…AD8 at nonce 0). SPEC 14A. */
export const VECTRA_ADDRESS =
  (process.env.NEXT_PUBLIC_VECTRA_ADDRESS as `0x${string}`) ??
  "0xd24424Cc482D68b19e82aa7A6411C48aeD22215B";

/** True once the address holds code. Checked at runtime, never assumed. */
export const USDC = "0xB6CEceAB302E2E4948951eE7843FC24E92933061" as const;
export const USDC_DECIMALS = 6;

/** Verified live, SPEC 13. Router and spender differ; both are shown. */
export const ROUTER = "0x7c5bEE2a8091C3ef39072f64F18Fac913060AEaF" as const;
export const SPENDER = "0x8b773D83bc66Be128c60e07E17C8901f7a64F000" as const;

/** The recorder's committed output, read raw. No database. */
export const DATA_BASE =
  process.env.NEXT_PUBLIC_DATA_BASE ??
  "https://raw.githubusercontent.com/Lideeyah/vectra/main/data";

export const explorerTx = (h: string) => `${CHAIN.explorer}/tx/${h}`;
export const explorerAddress = (a: string) => `${CHAIN.explorer}/address/${a}`;
