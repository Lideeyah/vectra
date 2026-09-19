/**
 * Creation, end to end against the anvil fork.
 *
 * Rendering has been verified; working has not. This signs BOTH transactions
 * with a real key, then reads the mandate back FROM CHAIN and compares it
 * against what the form described — never against the form's own state, since
 * a units or encoding error between the two is exactly what would agree with
 * itself and disagree with the contract.
 */
import {
  createPublicClient, createWalletClient, defineChain, erc20Abi, http, type Address,
} from "viem";
import { privateKeyToAccount } from "viem/accounts";
import { VECTRA_ABI } from "../lib/abi";
import { buildCreateParams } from "../lib/createParams";

const RPC = process.env.RPC ?? "http://127.0.0.1:8545";
const VECTRA = (process.env.VECTRA ?? "") as Address;
const USDC = "0xB6CEceAB302E2E4948951eE7843FC24E92933061" as Address;
const KEY = "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d" as const;

const NVDAX = "0xc845b2894dBddd03858fd2D643B4eF725fE0849d" as Address;
const TSLAX = "0x8aD3c73F833d3F9A523aB01476625F269aEB7Cf0" as Address;

const chain = defineChain({
  id: 196, name: "X Layer",
  nativeCurrency: { name: "OKB", symbol: "OKB", decimals: 18 },
  rpcUrls: { default: { http: [RPC] } },
});

const pub = createPublicClient({ chain, transport: http(RPC) });
const account = privateKeyToAccount(KEY);
const wallet = createWalletClient({ account, chain, transport: http(RPC) });

let failures = 0;
function check(name: string, actual: unknown, expected: unknown) {
  const ok = String(actual) === String(expected);
  if (!ok) failures++;
  console.log(`${ok ? "  ok  " : "  FAIL"} ${name.padEnd(14)} chain=${actual}  form=${expected}`);
}

async function main() {
  if (!VECTRA) throw new Error("set VECTRA=<address>");

  const form = {
    tokens: [NVDAX, TSLAX] as Address[],
    targetsDecimal: ["4.5", "0.25"],
    capUsd: "37.50",
    legUsd: "2.25",
    ratePct: "15",
    driftPct: "2.5",
    days: "14",
    agent: "0x70997970C51812dc3A010C7d01b50e0d17dc79C8" as Address,
    nowSeconds: Math.floor(Date.now() / 1000),
  };
  const p = buildCreateParams(form);
  console.log("form -> params");
  console.log("  targetShares", p.targetShares.map(String).join(", "));
  console.log("  totalCapUsdc", p.totalCapUsdc.toString(), " maxLegUsdc", p.maxLegUsdc.toString());
  console.log("  driftBps", p.driftBps, " rateBps", p.maxLegBpsOfTarget);

  console.log("\ntransaction 1 of 2: approve");
  const a = await wallet.writeContract({
    address: USDC, abi: erc20Abi, functionName: "approve", args: [VECTRA, p.totalCapUsdc],
  });
  await pub.waitForTransactionReceipt({ hash: a });
  console.log("  approved");

  console.log("transaction 2 of 2: createMandate");
  const c = await wallet.writeContract({
    address: VECTRA, abi: VECTRA_ABI, functionName: "createMandate", args: [p],
  });
  const rc = await pub.waitForTransactionReceipt({ hash: c });
  console.log("  created, status", rc.status);

  const id = (await pub.readContract({
    address: VECTRA, abi: VECTRA_ABI, functionName: "activeMandateOf", args: [account.address],
  })) as bigint;
  const m = (await pub.readContract({
    address: VECTRA, abi: VECTRA_ABI, functionName: "mandate", args: [id],
  })) as readonly unknown[];
  const b = (await pub.readContract({
    address: VECTRA, abi: VECTRA_ABI, functionName: "basket", args: [id],
  })) as [readonly Address[], readonly number[], readonly bigint[]];

  console.log(`\nread back mandate ${id} from chain:`);
  check("owner", m[0], account.address);
  check("agent", m[1], form.agent);
  check("expiry", m[2], p.expiry);
  check("driftBps", m[5], p.driftBps);
  check("maxLegUsdc", m[6], p.maxLegUsdc);
  check("totalCapUsdc", m[7], p.totalCapUsdc);
  check("spentUsdc", m[8], 0n);
  check("version", m[9], 1n);
  check("tokens", b[0].join(","), form.tokens.join(","));
  check("weightsBps", b[1].join(","), p.weightsBps.join(","));
  check("targetShares", b[2].join(","), p.targetShares.join(","));

  console.log(`\n${failures === 0 ? "PASS" : `FAIL (${failures})`} — chain agrees with the form`);
  process.exit(failures === 0 ? 0 : 1);
}

main().catch((e) => { console.error(String(e).slice(0, 400)); process.exit(1); });
