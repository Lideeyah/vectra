import { publicClient } from "./chain";
import { VECTRA_ABI } from "./abi";
import { VECTRA_ADDRESS } from "./config";
import type { Address } from "viem";
import type { MandateView } from "@/components/Rules";

/**
 * mandate() is read BY NAMED COMPONENT, never positionally.
 *
 * The tuple is fixed at deployment and its arity already changed once, from 9
 * to 10, when target versioning was added — which broke positional
 * destructuring in three test files. Positional reads are how an arity change
 * becomes a silent type-level failure rather than a loud one, and the contract
 * is immutable so the shape can never be corrected afterwards.
 *
 * This maps the result onto the ABI's declared output names and throws if a
 * name is missing, so a shape change fails here with a readable message.
 */
export async function readMandate(id: bigint): Promise<MandateView> {
  const raw = (await publicClient.readContract({
    address: VECTRA_ADDRESS,
    abi: VECTRA_ABI,
    functionName: "mandate",
    args: [id],
  })) as readonly unknown[];

  const spec = VECTRA_ABI.find(
    (f) => f.type === "function" && f.name === "mandate"
  ) as { outputs: readonly { name: string }[] };

  const byName = new Map<string, unknown>();
  spec.outputs.forEach((o, i) => byName.set(o.name, raw[i]));

  const need = <T,>(name: string): T => {
    if (!byName.has(name)) {
      throw new Error(`mandate(): ABI has no output named "${name}" — shape changed`);
    }
    return byName.get(name) as T;
  };

  return {
    owner: need<Address>("owner_"),
    agent: need<Address>("agent"),
    expiry: need<bigint>("expiry"),
    paused: need<boolean>("paused"),
    revoked: need<boolean>("revoked"),
    driftBps: Number(need<bigint | number>("driftBps")),
    maxLegUsdc: need<bigint>("maxLegUsdc"),
    totalCapUsdc: need<bigint>("totalCapUsdc"),
    spentUsdc: need<bigint>("spentUsdc"),
    version: BigInt(need<bigint | number>("version")),
  };
}

export async function readPosition(id: bigint) {
  const [tokens, current, target] = (await publicClient.readContract({
    address: VECTRA_ADDRESS,
    abi: VECTRA_ABI,
    functionName: "position",
    args: [id],
  })) as [readonly Address[], readonly bigint[], readonly bigint[]];
  return { tokens, current, target };
}

export async function readActiveMandateOf(owner: Address): Promise<bigint> {
  return (await publicClient.readContract({
    address: VECTRA_ADDRESS,
    abi: VECTRA_ABI,
    functionName: "activeMandateOf",
    args: [owner],
  })) as bigint;
}
