"use client";

import { useEffect, useState } from "react";
import { createWalletClient, custom, erc20Abi, type Address, type Hash } from "viem";
import { VECTRA_ABI } from "@/lib/abi";
import { CHAIN, USDC, VECTRA_ADDRESS, explorerTx } from "@/lib/config";
import { publicClient, xlayer } from "@/lib/chain";

/**
 * The two owner transactions: approve, then create.
 *
 * Signed by the MANDATE OWNER (the OKX wallet holding the USDC), not the
 * deployer. Both are ordinary transactions, which that wallet signs fine — it
 * only refuses contract creation.
 *
 * Every number here is derived, not typed: targets come from prices in the
 * recorded depth run and multipliers read from chain, and the cap is set below
 * the balance rather than at an aspirational figure, because the cap is the
 * loss bound.
 */
const AGENT = "0x083dCd15548a5a6504F774C7f16D28A454BfD656" as Address;

const BASKET = [
  { sym: "NVDAx", address: "0xc845b2894dbddd03858fd2d643b4ef725fe0849d" as Address,
    weightBps: 3400, target: 6055876421789847n, priceUsd: 224.1939 },
  { sym: "TSLAx", address: "0x8ad3c73f833d3f9a523ab01476625f269aeb7cf0" as Address,
    weightBps: 3300, target: 3570920269471138n, priceUsd: 369.6526 },
  { sym: "AAPLx", address: "0x9d275685dc284c8eb1c79f6aba7a63dc75ec890a" as Address,
    weightBps: 3300, target: 3924013832507040n, priceUsd: 335.2942 },
];

const TOTAL_CAP = 4_000_000n;   // $4.00 — the loss bound, under the balance
const MAX_LEG = 1_000_000n;     // $1.00 — routes on every constituent
const DRIFT_BPS = 500;          // 5%
const RATE_BPS = 2000;          // 20% of a target per leg
const DAYS = 14;
const PRICED_AT = "2026-09-21T09:07:40Z";

type Eth = { request: (a: { method: string; params?: unknown[] }) => Promise<unknown> };

export default function Create() {
  const [log, setLog] = useState<string[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const say = (s: string) => setLog((l) => [...l, s]);

  const [wallets, setWallets] = useState<{ name: string; provider: unknown }[]>([]);
  const [picked, setPicked] = useState<{ name: string; provider: unknown } | null>(null);
  const [bal, setBal] = useState<bigint | null>(null);
  const [allowance, setAllowance] = useState<bigint | null>(null);
  const [account, setAccount] = useState<Address | null>(null);

  useEffect(() => {
    const found: { name: string; provider: unknown }[] = [];
    const onAnnounce = (e: Event) => {
      const d = (e as CustomEvent).detail as { info: { name: string }; provider: unknown };
      if (found.some((w) => w.name === d.info.name)) return;
      found.push({ name: d.info.name, provider: d.provider });
      setWallets([...found]);
    };
    window.addEventListener("eip6963:announceProvider", onAnnounce);
    window.dispatchEvent(new Event("eip6963:requestProvider"));
    return () => window.removeEventListener("eip6963:announceProvider", onAnnounce);
  }, []);

  const eth = () => picked?.provider as Eth;

  const refresh = async (from: Address) => {
    const [b, a] = await Promise.all([
      publicClient.readContract({ address: USDC, abi: erc20Abi, functionName: "balanceOf", args: [from] }),
      publicClient.readContract({ address: USDC, abi: erc20Abi, functionName: "allowance", args: [from, VECTRA_ADDRESS] }),
    ]);
    setBal(b as bigint);
    setAllowance(a as bigint);
  };

  const connect = async (w: { name: string; provider: unknown }) => {
    setPicked(w);
    setLog([`selected ${w.name}`]);
    const e = w.provider as Eth;
    const accts = (await e.request({ method: "eth_requestAccounts" })) as string[];
    const from = accts[0] as Address;
    setAccount(from);
    say(`account ${from}`);
    const chainIdHex = (await e.request({ method: "eth_chainId" })) as string;
    if (Number(chainIdHex) !== CHAIN.id) {
      say(`wallet is on chain ${Number(chainIdHex)} — switch to ${CHAIN.name} (${CHAIN.id})`);
      return;
    }
    await refresh(from);
  };

  const wallet = (from: Address) =>
    createWalletClient({ account: from, chain: xlayer, transport: custom(eth() as never) });

  const send = async (label: string, fn: () => Promise<Hash>) => {
    setBusy(label);
    try {
      const hash = await fn();
      say(`tx ${hash}`);
      const r = await publicClient.waitForTransactionReceipt({ hash });
      say(`status ${r.status}, gas ${r.gasUsed}`);
      if (r.status !== "success") throw new Error(`${label} reverted`);
      if (account) await refresh(account);
      return r;
    } catch (e) {
      say(`ERROR: ${e instanceof Error ? e.message.split("\n")[0] : String(e)}`);
      console.error(e);
      return null;
    } finally {
      setBusy(null);
    }
  };

  const doApprove = async () => {
    if (!account) return;
    say(`approving $${(Number(TOTAL_CAP) / 1e6).toFixed(2)} — exactly the cap, not unlimited`);
    await send("approve", () =>
      wallet(account).writeContract({
        address: USDC, abi: erc20Abi, functionName: "approve",
        args: [VECTRA_ADDRESS, TOTAL_CAP],
      }),
    );
  };

  const doCreate = async () => {
    if (!account) return;
    const expiry = BigInt(Math.floor(Date.now() / 1000) + DAYS * 86400);
    const params = {
      tokens: BASKET.map((b) => b.address),
      weightsBps: BASKET.map((b) => b.weightBps),
      targetShares: BASKET.map((b) => b.target),
      driftBps: DRIFT_BPS,
      maxLegUsdc: MAX_LEG,
      totalCapUsdc: TOTAL_CAP,
      maxLegBpsOfTarget: RATE_BPS,
      expiry,
      agent: AGENT,
    };
    say("creating mandate…");
    const r = await send("createMandate", () =>
      wallet(account).writeContract({
        address: VECTRA_ADDRESS, abi: VECTRA_ABI, functionName: "createMandate", args: [params],
      }),
    );
    if (!r) return;
    // Read it back FROM CHAIN. What the transaction returned is not evidence of
    // what the contract stored.
    const id = (await publicClient.readContract({
      address: VECTRA_ADDRESS, abi: VECTRA_ABI, functionName: "activeMandateOf", args: [account],
    })) as bigint;
    say(`mandate id ${id}`);
    const pos = (await publicClient.readContract({
      address: VECTRA_ADDRESS, abi: VECTRA_ABI, functionName: "position", args: [id],
    })) as [readonly Address[], readonly bigint[], readonly bigint[]];
    pos[0].forEach((t, i) => {
      const b = BASKET.find((x) => x.address.toLowerCase() === t.toLowerCase());
      say(`  ${b?.sym ?? t}: held ${pos[1][i]} target ${pos[2][i]}`);
    });
    say("MANDATE LIVE");
  };

  const usd = (v: bigint | null) => (v === null ? "—" : `$${(Number(v) / 1e6).toFixed(6)}`);
  const onChain = account !== null;

  return (
    <div className="wrap" style={{ paddingTop: 48, paddingBottom: 80 }}>
      <h1 style={{ fontSize: 20, fontWeight: 500 }}>Create the mandate</h1>
      <p className="dim" style={{ fontSize: 13, maxWidth: 640 }}>
        Two transactions, signed by the owner wallet holding the USDC. Contract{" "}
        <span className="mono">{VECTRA_ADDRESS}</span>.
      </p>

      <div style={{ marginTop: 20 }}>
        <div className="dim" style={{ fontSize: 12, marginBottom: 8 }}>
          WALLET {picked ? `— ${picked.name}` : "— choose the OWNER wallet (the one with the USDC)"}
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {wallets.length === 0 && <span className="faint" style={{ fontSize: 12 }}>none announced</span>}
          {wallets.map((w) => (
            <button key={w.name} className="btn" onClick={() => void connect(w)}
              style={picked?.name === w.name ? { borderColor: "var(--cyan)", color: "var(--cyan)" } : undefined}>
              {w.name}
            </button>
          ))}
        </div>
      </div>

      <div style={{ border: "1px solid var(--bone-12)", padding: 18, marginTop: 20 }}>
        <Row label="Your USDC" value={usd(bal)} />
        <Row label="Total cap — the loss bound" value={usd(TOTAL_CAP)} />
        <Row label="Max per buy" value={usd(MAX_LEG)} />
        <Row label="Drift tolerance" value={`${DRIFT_BPS / 100}%`} />
        <Row label="Max movement per leg" value={`${RATE_BPS / 100}% of target, in shares`} />
        <Row label="Expiry" value={`${DAYS} days`} />
        <Row label="Agent" value={AGENT} />
        <Row label="Current allowance" value={usd(allowance)} />
      </div>

      <div style={{ border: "1px solid var(--bone-12)", padding: 18, marginTop: 12 }}>
        <div className="dim" style={{ fontSize: 12, marginBottom: 10 }}>
          BASKET — targets in shares, from prices recorded {PRICED_AT}
        </div>
        {BASKET.map((b) => (
          <div key={b.address} style={{ display: "flex", justifyContent: "space-between", gap: 12, padding: "6px 0", fontSize: 13, flexWrap: "wrap" }}>
            <span>{b.sym} <span className="faint">{b.weightBps / 100}% @ ${b.priceUsd}</span></span>
            <span className="mono" style={{ fontSize: 12 }}>{b.target.toString()}</span>
          </div>
        ))}
      </div>

      <div style={{ display: "flex", gap: 10, marginTop: 18, flexWrap: "wrap" }}>
        <button className="btn" disabled={!onChain || !!busy} onClick={doApprove}>
          {busy === "approve" ? "approving…" : "1 · Approve $4.00"}
        </button>
        <button className="btn" disabled={!onChain || !!busy || (allowance ?? 0n) < TOTAL_CAP} onClick={doCreate}>
          {busy === "createMandate" ? "creating…" : "2 · Create mandate"}
        </button>
      </div>

      {(allowance ?? 0n) < TOTAL_CAP && onChain && (
        <p className="faint" style={{ fontSize: 12, marginTop: 8 }}>
          Create unlocks once the allowance covers the cap.
        </p>
      )}

      {log.length > 0 && (
        <pre className="mono" style={{ fontSize: 12, marginTop: 20, whiteSpace: "pre-wrap", wordBreak: "break-all" }}>
          {log.join("\n")}
        </pre>
      )}
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", gap: 12, padding: "6px 0", fontSize: 13, flexWrap: "wrap" }}>
      <span>{label}</span>
      <span className="mono" style={{ fontSize: 12 }}>{value}</span>
    </div>
  );
}
