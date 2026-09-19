/**
 * The rejected-creation path, end to end.
 *
 * The dangling-approval detection has never seen a real dangling approval. This
 * grants one, then fails the creation on purpose, and confirms that what is
 * left behind is exactly what the interface claims to detect: an allowance with
 * no mandate behind it.
 */
import { createPublicClient, createWalletClient, defineChain, erc20Abi, http, type Address } from "viem";
import { privateKeyToAccount } from "viem/accounts";
import { VECTRA_ABI } from "../lib/abi";

const RPC = process.env.RPC ?? "http://127.0.0.1:8545";
const V = (process.env.VECTRA ?? "") as Address;
const USDC = "0xB6CEceAB302E2E4948951eE7843FC24E92933061" as Address;
const NVDAX = "0xc845b2894dBddd03858fd2D643B4eF725fE0849d" as Address;
const chain = defineChain({ id: 196, name: "X Layer", nativeCurrency: { name: "OKB", symbol: "OKB", decimals: 18 }, rpcUrls: { default: { http: [RPC] } } });
const pub = createPublicClient({ chain, transport: http(RPC) });
// anvil #3 — untouched, so the starting state is genuinely clean.
const acct = privateKeyToAccount("0x7c852118294e51e653712a81e05800f419141751be58f605c371e15141b007a6");
const wallet = createWalletClient({ account: acct, chain, transport: http(RPC) });

let fails = 0;
const check = (n: string, ok: boolean, detail = "") => {
  if (!ok) fails++;
  console.log(`  ${ok ? "ok  " : "FAIL"} ${n}${detail ? "  " + detail : ""}`);
};

async function allowance() {
  return (await pub.readContract({ address: USDC, abi: erc20Abi, functionName: "allowance", args: [acct.address, V] })) as bigint;
}
async function mandateId() {
  return (await pub.readContract({ address: V, abi: VECTRA_ABI, functionName: "activeMandateOf", args: [acct.address] })) as bigint;
}

async function main() {
  if (!V) throw new Error("set VECTRA=<address>");
  console.log("starting state");
  check("no allowance", (await allowance()) === 0n, `allowance=${await allowance()}`);
  check("no mandate", (await mandateId()) === 0n);

  console.log("\ntransaction 1 of 2: approve (accepted)");
  const cap = 25_000_000n;
  const a = await wallet.writeContract({ address: USDC, abi: erc20Abi, functionName: "approve", args: [V, cap] });
  await pub.waitForTransactionReceipt({ hash: a });
  check("allowance granted", (await allowance()) === cap, `${await allowance()}`);

  console.log("\ntransaction 2 of 2: createMandate (REJECTED — weights do not sum to 10000)");
  const blk = await pub.getBlock();
  try {
    await wallet.writeContract({
      address: V, abi: VECTRA_ABI, functionName: "createMandate",
      args: [{
        tokens: [NVDAX], weightsBps: [9999], targetShares: [10n ** 18n],
        driftBps: 500, maxLegUsdc: 5_000_000n, totalCapUsdc: cap,
        expiry: blk.timestamp + 2592000n, maxLegBpsOfTarget: 2000, agent: acct.address,
      }],
    });
    check("creation should have failed", false);
  } catch (e) {
    const name = String(e).match(/Error:\s*(\w+)\(\)/)?.[1] ?? "reverted";
    check("creation rejected", true, `→ ${name}`);
  }

  console.log("\nwhat is left behind — the state the interface must detect");
  const left = await allowance();
  check("allowance still granted", left === cap, `${left}`);
  check("no mandate behind it", (await mandateId()) === 0n);
  check("this is a dangling approval", left > 0n && (await mandateId()) === 0n);

  console.log("\nrevoking, as the interface offers");
  const r = await wallet.writeContract({ address: USDC, abi: erc20Abi, functionName: "approve", args: [V, 0n] });
  await pub.waitForTransactionReceipt({ hash: r });
  check("allowance cleared", (await allowance()) === 0n);

  console.log(`\n${fails === 0 ? "PASS" : `FAIL (${fails})`}`);
  process.exit(fails === 0 ? 0 : 1);
}
main().catch((e) => { console.error(String(e).slice(0, 300)); process.exit(1); });
