"use client";

import { useCallback, useEffect, useState } from "react";
import { formatUnits, parseUnits, type Address } from "viem";
import type { Row } from "./Convergence";
import type { MandateView } from "./Rules";
import {
  amendTargets, pause, readAllowance, resume, revoke, revokeAllowance,
} from "@/lib/write";
import { usdc } from "@/lib/format";

/**
 * What the owner can do, and what the agent cannot.
 *
 * This exists because a mandate you can create but not stop is worse than no
 * mandate at all: it leaves a live USDC allowance with no way back. Revoke is
 * also the claim this product makes about custody — the owner keeps control —
 * and a claim with no button behind it is a slogan.
 *
 * The allowance is shown as a SEPARATE thing from the mandate throughout,
 * because it is one. The contract's own revoke says so: it moves no funds and
 * the owner must take back their approval themselves. Treating the two as one
 * action is how someone ends up believing they have exited when they have not.
 */
export function Controls({
  owner, id, m, rows, readOnly, onDone,
}: {
  owner: Address;
  id: bigint;
  m: MandateView;
  rows: Row[];
  readOnly?: boolean;
  onDone: () => void;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [confirmRevoke, setConfirmRevoke] = useState(false);
  const [allowance, setAllowance] = useState<bigint | null>(null);

  const refreshAllowance = useCallback(() => {
    readAllowance(owner).then(setAllowance).catch(() => setAllowance(null));
  }, [owner]);

  useEffect(refreshAllowance, [refreshAllowance]);

  const expired = m.expiry > 0n && BigInt(Math.floor(Date.now() / 1000)) >= m.expiry;

  const run = async (label: string, fn: () => Promise<unknown>) => {
    setErr(null);
    setBusy(label);
    try {
      await fn();
      refreshAllowance();
      onDone();
    } catch (e) {
      // The wallet's own words. A rejected signature and a reverted
      // transaction are different events and must not read the same.
      const msg = e instanceof Error ? e.message : String(e);
      setErr(msg.split("\n")[0]);
    } finally {
      setBusy(null);
      setConfirmRevoke(false);
    }
  };

  const status = m.revoked
    ? { text: "Revoked", note: "Permanent. The agent can do nothing with this mandate." }
    : expired
      ? { text: "Expired", note: "Past its expiry. The agent can no longer execute against it." }
      : m.paused
        ? { text: "Paused", note: "The agent cannot execute. Nothing has been sold or moved." }
        : { text: "Active", note: "The agent may execute within the limits above." };

  return (
    <section style={{ marginBottom: 48 }}>
      <div className="dim" style={{ fontSize: 12, letterSpacing: "0.08em", marginBottom: 14 }}>
        WHAT ONLY YOU CAN DO
      </div>

      <div style={{ border: "1px solid var(--bone-12)", padding: 18, marginBottom: 18 }}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
          <span style={{ fontSize: 14 }}>Mandate {id.toString()}</span>
          <span className="mono" style={{ fontSize: 14 }}>{status.text}</span>
        </div>
        <p className="dim" style={{ fontSize: 13, margin: "8px 0 0" }}>{status.note}</p>
      </div>

      {readOnly ? (
        <p className="dim" style={{ fontSize: 13, maxWidth: 640 }}>
          This is a read-only view of someone else&apos;s mandate. These actions
          are the owner&apos;s alone — the contract checks the caller, so there
          is nothing to disable here that the chain would not refuse anyway.
        </p>
      ) : (
        <>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 18 }}>
            {!m.revoked && !m.paused && (
              <button className="btn" disabled={!!busy}
                onClick={() => run("pause", () => pause(owner, id))}>
                {busy === "pause" ? "pausing…" : "Pause"}
              </button>
            )}
            {!m.revoked && m.paused && (
              <button className="btn" disabled={!!busy}
                onClick={() => run("resume", () => resume(owner, id))}>
                {busy === "resume" ? "resuming…" : "Resume"}
              </button>
            )}
            {!m.revoked && (
              confirmRevoke ? (
                <>
                  <button className="btn" disabled={!!busy}
                    onClick={() => run("revoke", () => revoke(owner, id))}>
                    {busy === "revoke" ? "revoking…" : "Yes, revoke permanently"}
                  </button>
                  <button className="btn" disabled={!!busy}
                    onClick={() => setConfirmRevoke(false)}>
                    Cancel
                  </button>
                </>
              ) : (
                <button className="btn" disabled={!!busy}
                  onClick={() => { setErr(null); setConfirmRevoke(true); }}>
                  Revoke
                </button>
              )
            )}
          </div>

          <p className="dim" style={{ fontSize: 13, margin: "0 0 18px", maxWidth: 640 }}>
            <strong style={{ color: "var(--bone)" }}>
              Pausing sells nothing.
            </strong>{" "}
            It stops the agent where it stands and is reversible. Revoking is
            permanent and cannot be resumed — it does not move funds either,
            because the contract never holds any.
          </p>

          {err && (
            <p className="mono" style={{ fontSize: 12, marginBottom: 18, wordBreak: "break-word" }}>
              {err}
            </p>
          )}
        </>
      )}

      <Allowance
        allowance={allowance}
        revoked={m.revoked}
        readOnly={readOnly}
        busy={busy}
        onRevoke={() => run("allowance", () => revokeAllowance(owner))}
      />

      {!readOnly && !m.revoked && (
        <Amend owner={owner} id={id} rows={rows} version={m.version}
               busy={busy} onRun={run} />
      )}
    </section>
  );
}

/**
 * The allowance, always separate from the mandate.
 *
 * Revoking the mandate does not touch it. The contract says as much in its own
 * comment, and someone who revokes and walks away still has a standing approval
 * unless this is on screen and actionable.
 */
function Allowance({
  allowance, revoked, readOnly, busy, onRevoke,
}: {
  allowance: bigint | null;
  revoked: boolean;
  readOnly?: boolean;
  busy: string | null;
  onRevoke: () => void;
}) {
  if (allowance === null) return null;
  const live = allowance > 0n;

  // Practically unbounded approvals are the common case and read as noise as a
  // raw number, so they are named rather than printed.
  const shown = allowance > 10n ** 24n ? "unlimited" : `$${usdc(allowance)}`;

  return (
    <div style={{ border: "1px solid var(--bone-12)", padding: 18, marginBottom: 18 }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
        <span style={{ fontSize: 14 }}>
          {readOnly ? "USDC the owner has approved the contract to spend"
                    : "USDC you have approved the contract to spend"}
        </span>
        <span className="mono" style={{ fontSize: 14 }}>{live ? shown : "none"}</span>
      </div>

      <p className="dim" style={{ fontSize: 13, margin: "8px 0 0", maxWidth: 640 }}>
        {live ? (
          <>
            This is a separate permission from the mandate, and revoking the
            mandate does not take it back.{" "}
            {revoked && (
              <strong style={{ color: "var(--bone)" }}>
                Your mandate is revoked and this approval is still standing.
              </strong>
            )}{" "}
            Nothing can spend it while no mandate is active, and only the
            owner can remove it.
          </>
        ) : (
          <>Nothing is approved. The contract cannot move your USDC.</>
        )}
      </p>

      {live && !readOnly && (
        <button className="btn" style={{ marginTop: 14 }} disabled={!!busy} onClick={onRevoke}>
          {busy === "allowance" ? "revoking…" : "Revoke allowance"}
        </button>
      )}
    </div>
  );
}

/**
 * Targets are held in SHARES, not dollars and not percentages, because shares
 * are the only quantity a rebase does not move. The editor works in the same
 * unit the contract stores, so what is typed is what is written.
 */
function Amend({
  owner, id, rows, version, busy, onRun,
}: {
  owner: Address;
  id: bigint;
  rows: Row[];
  version: bigint;
  busy: string | null;
  onRun: (label: string, fn: () => Promise<unknown>) => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [vals, setVals] = useState<string[]>(() =>
    rows.map((r) => formatUnits(r.target, 18)),
  );
  const [parseErr, setParseErr] = useState<string | null>(null);

  // Re-seed from chain whenever the mandate changes underneath the form, so an
  // open editor never writes back a stale target it was showing.
  useEffect(() => {
    setVals(rows.map((r) => formatUnits(r.target, 18)));
  }, [rows, version]);

  if (rows.length === 0) return null;

  const submit = () => {
    setParseErr(null);
    let parsed: bigint[];
    try {
      parsed = vals.map((v, i) => {
        const t = v.trim();
        if (t === "" || !/^\d*\.?\d*$/.test(t)) {
          throw new Error(`${rows[i].symbol}: "${v}" is not a number of shares`);
        }
        return parseUnits(t, 18);
      });
    } catch (e) {
      setParseErr(e instanceof Error ? e.message : String(e));
      return;
    }
    void onRun("amend", () => amendTargets(owner, id, parsed));
  };

  const changed = vals.some((v, i) => {
    try { return parseUnits(v.trim() || "0", 18) !== rows[i].target; } catch { return true; }
  });

  return (
    <div style={{ border: "1px solid var(--bone-12)", padding: 18 }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
        <span style={{ fontSize: 14 }}>Targets, in shares</span>
        <button className="btn" onClick={() => setOpen((o) => !o)}>
          {open ? "Close" : "Change targets"}
        </button>
      </div>

      <p className="dim" style={{ fontSize: 13, margin: "8px 0 0", maxWidth: 640 }}>
        Changing a target changes the distance to it without a single trade.
        That is allowed, and it is recorded: the contract emits the targets
        before and after and increments the version, so a gap that closed
        because the target moved cannot be passed off as one closed by
        rebalancing.
      </p>

      {open && (
        <div style={{ marginTop: 16 }}>
          {rows.map((r, i) => (
            <div key={r.address}
                 style={{ display: "flex", justifyContent: "space-between",
                          alignItems: "center", gap: 12, padding: "8px 0",
                          borderTop: "1px solid var(--bone-12)" }}>
              <span style={{ fontSize: 13 }}>
                {r.symbol}
                <span className="faint" style={{ fontSize: 12 }}>
                  {" "}now {formatUnits(r.target, 18)}
                </span>
              </span>
              <input
                className="mono"
                value={vals[i] ?? ""}
                inputMode="decimal"
                onChange={(e) =>
                  setVals((p) => p.map((v, j) => (j === i ? e.target.value : v)))
                }
                style={{ width: 200, fontSize: 13, padding: "6px 8px",
                         background: "transparent", color: "inherit",
                         border: "1px solid var(--bone-12)" }}
              />
            </div>
          ))}

          {parseErr && (
            <p className="mono" style={{ fontSize: 12, marginTop: 12 }}>{parseErr}</p>
          )}

          <button className="btn" style={{ marginTop: 14 }}
                  disabled={!!busy || !changed} onClick={submit}>
            {busy === "amend"
              ? "amending…"
              : changed ? "Write new targets" : "No change"}
          </button>
        </div>
      )}
    </div>
  );
}
