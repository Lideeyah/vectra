"use client";

import { createWalletClient, custom, erc20Abi, maxUint256, type Address, type Hash } from "viem";
import { VECTRA_ABI } from "./abi";
import { USDC, VECTRA_ADDRESS } from "./config";
import { injected, publicClient, xlayer } from "./chain";

/** The four owner-signed writes. The frontend never signs for the agent. */

function wallet(account: Address) {
  const eth = injected();
  if (!eth) throw new Error("no wallet");
  return createWalletClient({
    account,
    chain: xlayer,
    transport: custom(eth as never),
  });
}

export async function readAllowance(owner: Address): Promise<bigint> {
  return (await publicClient.readContract({
    address: USDC,
    abi: erc20Abi,
    functionName: "allowance",
    args: [owner, VECTRA_ADDRESS],
  })) as bigint;
}

/**
 * Step one of two. This is where the user takes on real risk, so the interface
 * says so in the clearest sentence on the site rather than treating it as a
 * formality.
 */
export async function approveUsdc(owner: Address, amount: bigint): Promise<Hash> {
  const hash = await wallet(owner).writeContract({
    address: USDC,
    abi: erc20Abi,
    functionName: "approve",
    args: [VECTRA_ADDRESS, amount],
  });
  await publicClient.waitForTransactionReceipt({ hash });
  return hash;
}

/** Revokes a dangling approval left by a creation that was rejected. */
export async function revokeAllowance(owner: Address): Promise<Hash> {
  return approveUsdc(owner, 0n);
}

export type CreateParams = {
  tokens: Address[];
  weightsBps: number[];
  targetShares: bigint[];
  driftBps: number;
  maxLegUsdc: bigint;
  totalCapUsdc: bigint;
  maxLegBpsOfTarget: number;
  expiry: bigint;
  agent: Address;
};

export async function createMandate(owner: Address, p: CreateParams): Promise<Hash> {
  const hash = await wallet(owner).writeContract({
    address: VECTRA_ADDRESS,
    abi: VECTRA_ABI,
    functionName: "createMandate",
    args: [p],
  });
  await publicClient.waitForTransactionReceipt({ hash });
  return hash;
}

export async function pause(owner: Address, id: bigint) {
  return owned(owner, "pause", id);
}
export async function resume(owner: Address, id: bigint) {
  return owned(owner, "resume", id);
}
export async function revoke(owner: Address, id: bigint) {
  return owned(owner, "revoke", id);
}

/**
 * Changing a target changes the distance without a single trade, which is why
 * the contract records the targets before and after and increments the version
 * rather than forbidding it. Amending is permitted and auditable, not secret.
 */
export async function amendTargets(
  owner: Address,
  id: bigint,
  targetShares: bigint[],
): Promise<Hash> {
  const hash = await wallet(owner).writeContract({
    address: VECTRA_ADDRESS,
    abi: VECTRA_ABI,
    functionName: "amendTargets",
    args: [id, targetShares],
  });
  await publicClient.waitForTransactionReceipt({ hash });
  return hash;
}

async function owned(owner: Address, fn: "pause" | "resume" | "revoke", id: bigint) {
  const hash = await wallet(owner).writeContract({
    address: VECTRA_ADDRESS,
    abi: VECTRA_ABI,
    functionName: fn,
    args: [id],
  });
  await publicClient.waitForTransactionReceipt({ hash });
  return hash;
}

export { maxUint256 };
