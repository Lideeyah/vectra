/**
 * The owner's controls, end to end against the anvil fork.
 *
 * Rendering a Pause button proves nothing. A hand-written ABI once had two
 * struct fields transposed, which changed a selector and made every call revert
 * with empty data while every test on the other side of that boundary agreed
 * with itself. The only thing that caught it was a positional caller against a
 * real chain, which is what this is: each control is SIGNED, then the resulting
 * state is read back FROM CHAIN rather than from what the call returned.
 *
 * It also asserts the uncomfortable one: that revoking the mandate leaves the
 * USDC allowance standing. The interface makes that claim in words, so it had
 * better be true.
 *
 * Prepare the chain first (anvil fork + deploy + seeded mandate):
 *   anvil --fork-url https://rpc.xlayer.tech &
 *   FOUNDRY_PROFILE=fork forge script script/DevLeg.s.sol --sig "setup()" \
 *     --rpc-url http://127.0.0.1:8545 --broadcast --unlocked
 *
 * Then:  VECTRA=0x… npx tsx scripts/e2e-controls.ts
 */
import {
  createPublicClient, createWalletClient, defineChain, erc20Abi, http,
  parseUnits, type Address,
} from "viem";
import { privateKeyToAccount } from "viem/accounts";
import { VECTRA_ABI } from "../lib/abi";

// Point the app's OWN config at this anvil before importing anything that
// reads it, so the reads below go through the interface's real code path
// rather than a second decoder written for the test. A test that reimplements
// the thing it is testing agrees with itself and proves nothing.
process.env.NEXT_PUBLIC_RPC = process.env.RPC ?? "http://127.0.0.1:8545";
process.env.NEXT_PUBLIC_VECTRA_ADDRESS = process.env.VECTRA ?? "";

const RPC = process.env.RPC ?? "http://127.0.0.1:8545";
const VECTRA = (process.env.VECTRA ?? "") as Address;
const USDC = "0xB6CEceAB302E2E4948951eE7843FC24E92933061" as Address;

/** anvil account 0 — the owner DevLeg's setup() creates the mandate for. */
const OWNER_KEY =
  "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80" as const;

const chain = defineChain({
  id: 196, name: "X Layer",
  nativeCurrency: { name: "OKB", symbol: "OKB", decimals: 18 },
  rpcUrls: { default: { http: [RPC] } },
});

const pub = createPublicClient({ chain, transport: http(RPC) });
const account = privateKeyToAccount(OWNER_KEY);
const wallet = createWalletClient({ account, chain, transport: http(RPC) });

let failures = 0;
function check(name: string, actual: unknown, expected: unknown) {
  const ok = String(actual) === String(expected);
  if (!ok) failures++;
  console.log(`  ${ok ? "ok  " : "FAIL"} ${name.padEnd(34)} chain=${actual} want=${expected}`);
}

/** Every write goes through the same path the interface uses: ABI + args. */
async function send(functionName: string, args: readonly unknown[]) {
  const hash = await wallet.writeContract({
    address: VECTRA, abi: VECTRA_ABI, functionName, args,
  } as never);
  const r = await pub.waitForTransactionReceipt({ hash });
  if (r.status !== "success") throw new Error(`${functionName} reverted`);
  return hash;
}

/**
 * The interface's own reader, imported rather than reimplemented. mandate()
 * returns TEN separate outputs, so viem hands back an array and any positional
 * read here would be the exact fragility lib/mandate.ts exists to prevent.
 */
async function main() {
  if (!VECTRA) throw new Error("set VECTRA=<address>");

  // Imported here rather than at the top so the env above is set before
  // lib/config reads it.
  const { readMandate, readPosition, readActiveMandateOf } =
    await import("../lib/mandate");
  const owner = account.address;

  const id = await readActiveMandateOf(owner);
  if (id === 0n) throw new Error(`no active mandate for ${owner} — run DevLeg setup() first`);
  console.log(`owner ${owner}\nmandate ${id}\n`);

  // --- pause -------------------------------------------------------------
  console.log("pause");
  await send("pause", [id]);
  check("paused after pause", (await readMandate(id)).paused, true);

  // --- resume ------------------------------------------------------------
  console.log("resume");
  await send("resume", [id]);
  check("paused after resume", (await readMandate(id)).paused, false);

  // --- amendTargets ------------------------------------------------------
  // The form works in decimal shares and parses with 18 decimals, so the same
  // conversion is exercised here rather than a hand-written integer.
  console.log("amendTargets");
  const prevVersion = (await readMandate(id)).version;
  const prevTargets = (await readPosition(id)).target;
  const next = prevTargets.map((_, i) => parseUnits(i === 0 ? "1.5" : "0.25", 18));

  await send("amendTargets", [id, next]);
  check("version incremented", (await readMandate(id)).version, prevVersion + 1n);
  (await readPosition(id)).target.forEach((t, i) => {
    check(`target[${i}] written`, t, next[i]);
  });

  // --- allowance BEFORE revoke -------------------------------------------
  // Approve something first, so the claim below is tested against a live
  // approval rather than against an account that never had one.
  console.log("approve USDC, then revoke the mandate");
  const approveHash = await wallet.writeContract({
    address: USDC, abi: erc20Abi, functionName: "approve", args: [VECTRA, 50_000_000n],
  });
  await pub.waitForTransactionReceipt({ hash: approveHash });

  const allowanceBefore = (await pub.readContract({
    address: USDC, abi: erc20Abi, functionName: "allowance", args: [owner, VECTRA],
  })) as bigint;
  check("allowance granted", allowanceBefore, 50_000_000n);

  // --- revoke ------------------------------------------------------------
  await send("revoke", [id]);
  check("revoked", (await readMandate(id)).revoked, true);
  check("activeMandateOf cleared", await readActiveMandateOf(owner), 0n);

  // THE CLAIM THE INTERFACE MAKES. Revoking the mandate must NOT touch the
  // allowance — if this ever came back 0, the interface would be telling
  // owners to take an action that had already happened, and the warning it
  // shows would be false.
  const allowanceAfter = (await pub.readContract({
    address: USDC, abi: erc20Abi, functionName: "allowance", args: [owner, VECTRA],
  })) as bigint;
  check("allowance SURVIVES revoke", allowanceAfter, 50_000_000n);

  // --- the way out -------------------------------------------------------
  console.log("revoke the allowance");
  const zeroHash = await wallet.writeContract({
    address: USDC, abi: erc20Abi, functionName: "approve", args: [VECTRA, 0n],
  });
  await pub.waitForTransactionReceipt({ hash: zeroHash });
  check("allowance zeroed", await pub.readContract({
    address: USDC, abi: erc20Abi, functionName: "allowance", args: [owner, VECTRA],
  }), 0n);

  // --- resume after revoke must FAIL -------------------------------------
  // A revoked mandate that could be resumed would make "permanent" a lie.
  console.log("resume after revoke (must revert)");
  let reverted = false;
  try {
    await send("resume", [id]);
  } catch {
    reverted = true;
  }
  check("resume refused after revoke", reverted, true);

  console.log(failures === 0 ? "\nALL CONTROLS PASS" : `\n${failures} FAILURE(S)`);
  process.exit(failures === 0 ? 0 : 1);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
