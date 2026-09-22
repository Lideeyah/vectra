"use client";

import { useEffect, useState } from "react";
import { createWalletClient, custom, type Address } from "viem";
import { VECTRA_ABI } from "@/lib/abi";
import { CHAIN, VECTRA_ADDRESS } from "@/lib/config";
import { publicClient, xlayer } from "@/lib/chain";

/**
 * Raise the targets by 8%, after the basket reached the old ones.
 *
 * The mandate converged: distance fell from 215.88% to 2.37%, inside the 5%
 * tolerance, so the agent stopped — convergence is terminal. Raising the
 * targets is the owner changing their mind, which is a thing this design
 * permits and records rather than prevents: the contract emits the old and new
 * values and increments the version, so a gap that closes because a target
 * moved can never be passed off as one closed by trading.
 *
 * Sized to fit: $0.316294 of the $0.446685 left under the cap, which puts the
 * basket 24.43% from target — far enough outside tolerance for the agent to
 * have real work, close enough that the cap can actually reach it.
 */
const NEW_TARGETS: bigint[] = [
  5794222226334229n,   // NVDAx
  3416632730382208n,   // TSLAx
  3754470299781204n,   // AAPLx
];

const ROWS = [
  { sym: "NVDAx", old: 5365020579939101n, next: NEW_TARGETS[0], usd: 0.116693 },
  { sym: "TSLAx", old: 3163548824427970n, next: NEW_TARGETS[1], usd: 0.100020 },
  { sym: "AAPLx", old: 3476361388686300n, next: NEW_TARGETS[2], usd: 0.099581 },
];

type Eth = { request: (a: { method: string; params?: unknown[] }) => Promise<unknown> };

export default function Amend() {
  const [log, setLog] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [wallets, setWallets] = useState<{ name: string; provider: unknown }[]>([]);
  const [picked, setPicked] = useState<{ name: string; provider: unknown } | null>(null);
  const [account, setAccount] = useState<Address | null>(null);
  const say = (s: string) => setLog((l) => [...l, s]);

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
    const r = [150, 500, 1200].map((ms) =>
      setTimeout(() => window.dispatchEvent(new Event("eip6963:requestProvider")), ms));
    return () => {
      window.removeEventListener("eip6963:announceProvider", onAnnounce);
      r.forEach(clearTimeout);
    };
  }, []);

  const connect = async (w: { name: string; provider: unknown }) => {
    setPicked(w);
    setLog([`selected ${w.name}`]);
    const e = w.provider as Eth;
    const a = (await e.request({ method: "eth_requestAccounts" })) as string[];
    setAccount(a[0] as Address);
    say(`account ${a[0]}`);
    const c = (await e.request({ method: "eth_chainId" })) as string;
    if (Number(c) !== CHAIN.id) say(`wrong chain ${Number(c)} — switch to ${CHAIN.id}`);
  };

  const run = async () => {
    if (!account || !picked) return;
    setBusy(true);
    try {
      const before = (await publicClient.readContract({
        address: VECTRA_ADDRESS, abi: VECTRA_ABI, functionName: "position", args: [1n],
      })) as [readonly Address[], readonly bigint[], readonly bigint[]];
      say(`targets before: ${before[2].map(String).join(", ")}`);

      const wallet = createWalletClient({
        account, chain: xlayer, transport: custom(picked.provider as never),
      });
      const hash = await wallet.writeContract({
        address: VECTRA_ADDRESS, abi: VECTRA_ABI,
        functionName: "amendTargets", args: [1n, NEW_TARGETS],
      });
      say(`tx ${hash}`);
      const r = await publicClient.waitForTransactionReceipt({ hash });
      say(`status ${r.status}, gas ${r.gasUsed}`);
      if (r.status !== "success") throw new Error("amendTargets reverted");

      // Read back from chain, not from what the call returned.
      const after = (await publicClient.readContract({
        address: VECTRA_ADDRESS, abi: VECTRA_ABI, functionName: "position", args: [1n],
      })) as [readonly Address[], readonly bigint[], readonly bigint[]];
      say(`targets after:  ${after[2].map(String).join(", ")}`);
      const m = (await publicClient.readContract({
        address: VECTRA_ADDRESS, abi: VECTRA_ABI, functionName: "mandate", args: [1n],
      })) as readonly unknown[];
      say(`version now ${String(m[9])}`);
      say("AMENDED — recorded in the target history with both values");
    } catch (e) {
      say(`ERROR: ${e instanceof Error ? e.message.split("\n")[0] : String(e)}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="wrap" style={{ paddingTop: 48, paddingBottom: 80 }}>
      <h1 style={{ fontSize: 20, fontWeight: 500 }}>Amend targets to fit the cap</h1>
      <p className="dim" style={{ fontSize: 13, maxWidth: 660 }}>
        Reaching the previous targets cost the basket to 2.37% from target, inside the 5% tolerance, so the agent stopped. These targets are 8% higher — $0.316294 of the $0.446685 left under the cap — which gives it work again. The change is recorded on chain with both values and a version increment. Signed by the owner.
      </p>

      <div style={{ marginTop: 18 }}>
        <div className="dim" style={{ fontSize: 12, marginBottom: 8 }}>
          WALLET {picked ? `— ${picked.name}` : "— choose the OWNER wallet"}
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

      <div style={{ border: "1px solid var(--bone-12)", padding: 18, marginTop: 18 }}>
        {ROWS.map((r) => (
          <div key={r.sym} style={{ padding: "8px 0", borderTop: "1px solid var(--bone-12)", fontSize: 13 }}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
              <span>{r.sym}</span>
              <span className="mono" style={{ fontSize: 12 }}>
                {r.old.toString()} → {r.next.toString()}
              </span>
            </div>
            <div className="faint" style={{ fontSize: 12 }}>costs ${r.usd.toFixed(6)} to reach</div>
          </div>
        ))}
      </div>

      <button className="btn" style={{ marginTop: 18 }} disabled={!account || busy} onClick={run}>
        {busy ? "amending…" : "Amend targets"}
      </button>

      {log.length > 0 && (
        <pre className="mono" style={{ fontSize: 12, marginTop: 20, whiteSpace: "pre-wrap", wordBreak: "break-all" }}>
          {log.join("\n")}
        </pre>
      )}
    </div>
  );
}
