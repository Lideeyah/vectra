"use client";

import { createPublicClient, defineChain, http, type Address } from "viem";
import { CHAIN } from "./config";

/**
 * defineChain rather than a bare object: casting the chain to `never` to make
 * it fit collapses viem's generics, and writeContract then rejects every call
 * with a type error that describes the cast rather than the problem.
 */
export const xlayer = defineChain({
  id: CHAIN.id,
  name: CHAIN.name,
  nativeCurrency: CHAIN.currency,
  rpcUrls: { default: { http: [CHAIN.rpc] } },
  blockExplorers: { default: { name: "OKLink", url: CHAIN.explorer } },
});

export const publicClient = createPublicClient({
  chain: xlayer,
  transport: http(CHAIN.rpc),
});

type Eth = {
  request: (a: { method: string; params?: unknown[] }) => Promise<unknown>;
  on?: (e: string, h: (...a: unknown[]) => void) => void;
  removeListener?: (e: string, h: (...a: unknown[]) => void) => void;
};

export function injected(): Eth | null {
  if (typeof window === "undefined") return null;
  return (window as unknown as { ethereum?: Eth }).ethereum ?? null;
}

/** Distinguishes "no wallet installed" from "wallet locked" — different states. */
export async function walletState(): Promise<
  { kind: "none" } | { kind: "locked" } | { kind: "ready"; address: Address; chainId: number }
> {
  const eth = injected();
  if (!eth) return { kind: "none" };
  const accounts = (await eth.request({ method: "eth_accounts" })) as string[];
  if (!accounts?.length) return { kind: "locked" };
  const chainIdHex = (await eth.request({ method: "eth_chainId" })) as string;
  return {
    kind: "ready",
    address: accounts[0] as Address,
    chainId: parseInt(chainIdHex, 16),
  };
}

export async function connect(): Promise<Address> {
  const eth = injected();
  if (!eth) throw new Error("no wallet");
  const accounts = (await eth.request({ method: "eth_requestAccounts" })) as string[];
  return accounts[0] as Address;
}

/**
 * Switch, then ADD on failure. Most wallets will not have X Layer configured,
 * and assuming the switch path is where a demo breaks in front of a judge.
 */
export async function switchToXLayer(): Promise<void> {
  const eth = injected();
  if (!eth) throw new Error("no wallet");
  const hexId = `0x${CHAIN.id.toString(16)}`;
  try {
    await eth.request({
      method: "wallet_switchEthereumChain",
      params: [{ chainId: hexId }],
    });
  } catch {
    await eth.request({
      method: "wallet_addEthereumChain",
      params: [
        {
          chainId: hexId,
          chainName: CHAIN.name,
          nativeCurrency: CHAIN.currency,
          rpcUrls: [CHAIN.rpc],
          blockExplorerUrls: [CHAIN.explorer],
        },
      ],
    });
  }
}

/** True when the configured address actually holds code. Never assumed. */
export async function contractDeployed(address: Address): Promise<boolean> {
  try {
    const code = await publicClient.getBytecode({ address });
    return !!code && code !== "0x";
  } catch {
    return false;
  }
}
