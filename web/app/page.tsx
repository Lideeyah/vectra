"use client";

import { useCallback, useEffect, useState } from "react";
import type { Address } from "viem";
import { Convergence, type Row } from "@/components/Convergence";
import { Proof } from "@/components/Proof";
import { Refusals } from "@/components/Refusals";
import { Rules, type MandateView } from "@/components/Rules";
import {
  LockedWallet, NoMandate, NotDeployed, NoWallet, RpcError, UnfundedMandate, WrongNetwork,
} from "@/components/States";
import { CHAIN, DATA_BASE, VECTRA_ADDRESS } from "@/lib/config";
import { connect, contractDeployed, switchToXLayer, walletState } from "@/lib/chain";
import { readActiveMandateOf, readMandate, readPosition } from "@/lib/mandate";
import { loadLatestCycle, type AgentCycle } from "@/lib/data";
import { addr } from "@/lib/format";

/** Cycles are five minutes; past two, the agent is not slow, it has stopped. */
const STALE_AFTER_MS = 12 * 60 * 1000;

type Phase =
  | { k: "loading" }
  | { k: "no-wallet" }
  | { k: "locked" }
  | { k: "wrong-network"; chainId: number }
  | { k: "not-deployed" }
  | { k: "rpc-error"; detail: string }
  | { k: "no-mandate"; owner: Address }
  | { k: "ready"; owner: Address; id: bigint; m: MandateView; rows: Row[] };

export default function Page() {
  const [phase, setPhase] = useState<Phase>({ k: "loading" });
  const [cycle, setCycle] = useState<AgentCycle | null>(null);

  const load = useCallback(async () => {
    setPhase({ k: "loading" });

    const w = await walletState();
    if (w.kind === "none") return setPhase({ k: "no-wallet" });
    if (w.kind === "locked") return setPhase({ k: "locked" });
    if (w.chainId !== CHAIN.id) return setPhase({ k: "wrong-network", chainId: w.chainId });

    if (!(await contractDeployed(VECTRA_ADDRESS))) return setPhase({ k: "not-deployed" });

    // An RPC failure must never render as "no mandate": identical on screen,
    // opposite in meaning.
    try {
      const id = await readActiveMandateOf(w.address);
      if (id === 0n) return setPhase({ k: "no-mandate", owner: w.address });

      const [m, pos] = await Promise.all([readMandate(id), readPosition(id)]);
      const rows: Row[] = pos.tokens.map((t, i) => ({
        symbol: addr(t),
        address: t,
        current: pos.current[i],
        target: pos.target[i],
      }));
      setPhase({ k: "ready", owner: w.address, id, m, rows });
    } catch (e) {
      setPhase({ k: "rpc-error", detail: e instanceof Error ? e.message : String(e) });
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  // The agent's own published decision, on a stable path. Never recomputed
  // here: two implementations of the same decision will eventually disagree,
  // and the one on screen would then be a lie.
  useEffect(() => {
    let live = true;
    const pull = async () => {
      const c = await loadLatestCycle();
      if (live) setCycle(c);
    };
    void pull();
    const t = setInterval(pull, 60_000);
    return () => { live = false; clearInterval(t); };
  }, []);

  // Re-render on a timer so "time since last cycle" counts rather than freezes.
  const [, tick] = useState(0);
  useEffect(() => {
    const t = setInterval(() => tick((n) => n + 1), 1000);
    return () => clearInterval(t);
  }, []);

  const doConnect = useCallback(async () => {
    try { await connect(); await load(); } catch { /* user rejected */ }
  }, [load]);

  const doSwitch = useCallback(async () => {
    try { await switchToXLayer(); await load(); } catch { /* user rejected */ }
  }, [load]);

  const stale = cycle ? Date.now() - Date.parse(cycle.ts) > STALE_AFTER_MS : false;
  const unfunded =
    phase.k === "ready" && phase.rows.length > 0 && phase.rows.every((r) => r.current === 0n);

  return (
    <div className="wrap" style={{ paddingTop: 48, paddingBottom: 80 }}>
      <Header />

      {phase.k === "loading" && (
        <p className="dim mono" style={{ fontSize: 13 }}>reading chain…</p>
      )}
      {phase.k === "no-wallet" && <NoWallet />}
      {phase.k === "locked" && <LockedWallet onConnect={doConnect} />}
      {phase.k === "wrong-network" && <WrongNetwork chainId={phase.chainId} onSwitch={doSwitch} />}
      {phase.k === "not-deployed" && <NotDeployed />}
      {phase.k === "rpc-error" && <RpcError detail={phase.detail} onRetry={load} />}
      {phase.k === "no-mandate" && <NoMandate owner={phase.owner} />}

      {phase.k === "ready" && (
        <>
          {unfunded && <UnfundedMandate />}
          <Convergence rows={phase.rows} toleranceBps={phase.m.driftBps} />
          <Refusals cycle={cycle} stale={stale} />
          <Rules m={phase.m} rateBps={null} />
        </>
      )}

      <Proof deployed={phase.k === "ready" || phase.k === "no-mandate"} dataBase={DATA_BASE} />
    </div>
  );
}

function Header() {
  return (
    <header style={{ marginBottom: 48 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <Mark />
        <span style={{ fontSize: 17, fontWeight: 600, letterSpacing: "-0.01em" }}>Vectra</span>
      </div>
      <p className="dim" style={{ fontSize: 14, margin: "14px 0 0", maxWidth: 560 }}>
        A basket of tokenised equities that maintains itself, at any size. The
        number that matters is how far it is from target, not what it is worth.
      </p>
    </header>
  );
}

/** The mark: a hairline circle, a cyan disc offset by ~8% of the radius. */
function Mark() {
  return (
    <svg width="22" height="22" viewBox="0 0 22 22" aria-label="Vectra">
      <circle cx="11" cy="11" r="10" fill="none" stroke="var(--bone)" strokeWidth="1" />
      <circle cx="11.8" cy="10.4" r="5.4" fill="var(--cyan)" />
    </svg>
  );
}
