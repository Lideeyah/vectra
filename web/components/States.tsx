"use client";

import { CHAIN, VECTRA_ADDRESS, explorerAddress } from "@/lib/config";
import { addr } from "@/lib/format";

/**
 * Every state below renders as itself. A state that falls through to a generic
 * error is a bug (SPEC 8), and an RPC failure rendering as "no mandate" is the
 * specific case that matters: they look identical and mean opposite things.
 */

export function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ border: "1px solid var(--bone-12)", padding: "28px 24px", maxWidth: 560 }}>
      {children}
    </div>
  );
}

export function NoWallet() {
  return (
    <Shell>
      <h2 style={{ margin: "0 0 10px", fontSize: 18, fontWeight: 600 }}>No wallet detected</h2>
      <p className="dim" style={{ fontSize: 14, margin: 0 }}>
        Vectra reads everything from chain, so a wallet is needed even to view a
        mandate you own. Install a browser wallet and reload.
      </p>
    </Shell>
  );
}

export function LockedWallet({ onConnect }: { onConnect: () => void }) {
  return (
    <Shell>
      <h2 style={{ margin: "0 0 10px", fontSize: 18, fontWeight: 600 }}>Wallet is locked</h2>
      <p className="dim" style={{ fontSize: 14, margin: "0 0 18px" }}>
        A wallet is installed but no account is available. Unlock it and connect.
      </p>
      <button className="btn btn-primary" onClick={onConnect}>Connect</button>
    </Shell>
  );
}

export function WrongNetwork({ chainId, onSwitch }: { chainId: number; onSwitch: () => void }) {
  return (
    <Shell>
      <h2 style={{ margin: "0 0 10px", fontSize: 18, fontWeight: 600 }}>Wrong network</h2>
      <p className="dim" style={{ fontSize: 14, margin: "0 0 6px" }}>
        Connected to chain <span className="mono">{chainId}</span>. Vectra is on{" "}
        <span className="mono">{CHAIN.name}</span>, chain{" "}
        <span className="mono">{CHAIN.id}</span>.
      </p>
      <p className="faint" style={{ fontSize: 12, margin: "0 0 18px" }}>
        If X Layer is not configured in your wallet, this adds it rather than
        failing.
      </p>
      <button className="btn btn-primary" onClick={onSwitch}>Switch to X Layer</button>
    </Shell>
  );
}

export function RpcError({ detail, onRetry }: { detail: string; onRetry: () => void }) {
  return (
    <Shell>
      <h2 className="red" style={{ margin: "0 0 10px", fontSize: 18, fontWeight: 600 }}>
        Could not read the chain
      </h2>
      <p className="dim" style={{ fontSize: 14, margin: "0 0 6px" }}>
        This is a read failure, <strong style={{ color: "var(--bone)" }}>not</strong> an
        empty mandate. The two look identical on screen and mean opposite things,
        so nothing is shown in its place.
      </p>
      <p className="mono faint" style={{ fontSize: 12, margin: "0 0 18px", wordBreak: "break-all" }}>
        {detail}
      </p>
      <button className="btn btn-secondary" onClick={onRetry}>Retry</button>
    </Shell>
  );
}

export function NotDeployed() {
  return (
    <Shell>
      <h2 style={{ margin: "0 0 10px", fontSize: 18, fontWeight: 600 }}>
        Contract not deployed yet
      </h2>
      <p className="dim" style={{ fontSize: 14, margin: "0 0 10px" }}>
        The address below holds no code on {CHAIN.name}. It is the predicted
        CREATE address the contract will occupy, and it is shown rather than
        hidden so the claim can be checked before there is anything to check.
      </p>
      <p className="mono" style={{ fontSize: 13, margin: 0, wordBreak: "break-all" }}>
        <a href={explorerAddress(VECTRA_ADDRESS)} target="_blank" rel="noreferrer">
          {VECTRA_ADDRESS}
        </a>
      </p>
    </Shell>
  );
}

export function NoMandate({ owner }: { owner: string }) {
  return (
    <Shell>
      <h2 style={{ margin: "0 0 10px", fontSize: 18, fontWeight: 600 }}>No mandate</h2>
      <p className="dim" style={{ fontSize: 14, margin: "0 0 10px" }}>
        <span className="mono">{addr(owner)}</span> does not own a mandate on this
        contract. Creating one takes two transactions: an allowance, then the
        mandate itself.
      </p>
      <p className="faint" style={{ fontSize: 12, margin: 0 }}>
        Creation is not built in this release.
      </p>
    </Shell>
  );
}

export function UnfundedMandate() {
  return (
    <div
      style={{
        border: "1px solid var(--orange)",
        padding: "14px 16px",
        marginBottom: 32,
        fontSize: 13,
      }}
    >
      <span className="orange" style={{ fontWeight: 600 }}>Mandate created, nothing bought yet.</span>{" "}
      <span className="dim">
        The target is set and the agent has not yet acted. This is an awaited
        first cycle, not an empty portfolio.
      </span>
    </div>
  );
}
