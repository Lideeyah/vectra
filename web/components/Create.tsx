"use client";

import { useEffect, useMemo, useState } from "react";
import type { Address } from "viem";
import { loadConstituents, type Constituents } from "@/lib/data";
import { VECTRA_ADDRESS } from "@/lib/config";
import { addr } from "@/lib/format";
import { buildCreateParams, toShares } from "@/lib/createParams";
import {
  approveUsdc, createMandate, readAllowance, revokeAllowance, maxUint256,
} from "@/lib/write";

type Step = "basket" | "targets" | "limits" | "review";

const AGENT_DEFAULT = "0x70997970C51812dc3A010C7d01b50e0d17dc79C8" as Address;

export function Create({ owner, onDone }: { owner: Address; onDone: () => void }) {
  const [set, setSet] = useState<Constituents | null>(null);
  const [step, setStep] = useState<Step>("basket");
  const [picked, setPicked] = useState<string[]>([]);
  const [targets, setTargets] = useState<Record<string, string>>({});
  const [capUsd, setCapUsd] = useState("50");
  const [legUsd, setLegUsd] = useState("5");
  const [ratePct, setRatePct] = useState("20");
  const [driftPct, setDriftPct] = useState("5");
  const [days, setDays] = useState("30");
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [dangling, setDangling] = useState<bigint | null>(null);

  useEffect(() => { void loadConstituents().then(setSet); }, []);

  /**
   * A creation rejected AFTER the allowance was granted leaves the contract
   * approved with no mandate behind it. That is detected on return rather than
   * left for the user to discover, and offered for revocation.
   */
  useEffect(() => {
    void readAllowance(owner).then((a) => setDangling(a > 0n ? a : null));
  }, [owner]);

  const chosen = useMemo(
    () => (set?.constituents ?? []).filter((c) => picked.includes(c.address)),
    [set, picked]
  );

  if (!set) {
    return <p className="dim mono" style={{ fontSize: 13 }}>loading the tradeable set…</p>;
  }

  const submit = async () => {
    setErr(null);
    try {
      // Built by the same function the end-to-end test exercises, so the
      // encoding the user signs is the encoding that was verified.
      const p = buildCreateParams({
        tokens: chosen.map((c) => c.address as Address),
        targetsDecimal: chosen.map((c) => targets[c.address] ?? "0"),
        capUsd, legUsd, ratePct, driftPct, days,
        agent: AGENT_DEFAULT,
        nowSeconds: Math.floor(Date.now() / 1000),
      });
      setBusy("Approving USDC — transaction 1 of 2");
      await approveUsdc(owner, p.totalCapUsdc);
      setBusy("Creating the mandate — transaction 2 of 2");
      await createMandate(owner, p);
      setBusy(null);
      onDone();
    } catch (e) {
      setBusy(null);
      setErr(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <section style={{ marginBottom: 48 }}>
      <div className="dim" style={{ fontSize: 12, letterSpacing: "0.08em", marginBottom: 6 }}>
        CREATE A MANDATE — {step.toUpperCase()}
      </div>
      <p className="faint" style={{ fontSize: 12, margin: "0 0 20px" }}>
        {set.quotable} of {set.xstocksOnChain} xStocks are routable on X Layer.
        Only those are offered — a mandate on the rest could never execute.
        Verified {set.fixedAt.slice(0, 10)} at ${set.probeNotionalUsd}.
      </p>

      {dangling !== null && (
        <div style={{ border: "1px solid var(--orange)", padding: "12px 14px", marginBottom: 20 }}>
          <div className="orange" style={{ fontSize: 13, fontWeight: 600, marginBottom: 4 }}>
            You have an unused allowance
          </div>
          <p className="dim" style={{ fontSize: 12, margin: "0 0 10px" }}>
            The contract is approved for USDC but you own no mandate. This is
            what a creation rejected after the approval leaves behind.
          </p>
          <button className="btn btn-destructive" onClick={() => void revokeAllowance(owner).then(() => setDangling(null))}>
            Revoke it
          </button>
        </div>
      )}

      {step === "basket" && (
        <>
          <div style={{ maxHeight: 320, overflowY: "auto", border: "1px solid var(--bone-12)" }}>
            {set.constituents.map((c) => {
              const on = picked.includes(c.address);
              return (
                <button
                  key={c.address}
                  onClick={() =>
                    setPicked((p) => (on ? p.filter((x) => x !== c.address) : [...p, c.address]))
                  }
                  className="btn"
                  style={{
                    display: "flex", width: "100%", justifyContent: "space-between",
                    borderBottom: "1px solid var(--bone-12)", padding: "10px 14px",
                    color: on ? "var(--cyan)" : "var(--bone)",
                  }}
                >
                  <span className="mono" style={{ fontSize: 13 }}>{c.symbol}</span>
                  <span className="mono faint" style={{ fontSize: 12 }}>{addr(c.address)}</span>
                </button>
              );
            })}
          </div>
          <Nav
            next={() => setStep("targets")}
            disabled={picked.length === 0 || picked.length > 10}
            label={`${picked.length} selected · continue`}
          />
        </>
      )}

      {step === "targets" && (
        <>
          <p className="dim" style={{ fontSize: 13, margin: "0 0 14px", maxWidth: 620 }}>
            Targets are set in <strong style={{ color: "var(--bone)" }}>shares</strong>,
            not dollars. A share target still means the same thing after a
            corporate action; a balance target does not, because a split changes
            every balance without a transfer. This is the number that gets signed.
          </p>
          {chosen.map((c) => (
            <div key={c.address} style={{ display: "flex", gap: 12, alignItems: "center", padding: "10px 0", borderTop: "1px solid var(--bone-12)" }}>
              <span className="mono" style={{ fontSize: 13, minWidth: 80 }}>{c.symbol}</span>
              <input
                className="mono"
                value={targets[c.address] ?? ""}
                onChange={(e) => setTargets((t) => ({ ...t, [c.address]: e.target.value }))}
                placeholder="0.0"
                inputMode="decimal"
                style={{
                  background: "transparent", border: "1px solid var(--bone-30)",
                  color: "var(--bone)", padding: "8px 10px", width: 140, fontSize: 13,
                }}
              />
              <span className="faint mono" style={{ fontSize: 12 }}>
                = {toShares(targets[c.address] ?? "0").toString()} wei of shares
              </span>
            </div>
          ))}
          <Nav next={() => setStep("limits")} disabled={chosen.some((c) => !Number(targets[c.address]))} label="continue" />
        </>
      )}

      {step === "limits" && (
        <>
          <Field label="Total USDC that may ever be spent" value={capUsd} set={setCapUsd} unit="USDC"
                 note="The loss bound. If the agent key were compromised and the router hostile, this is the most that can be lost." />
          <Field label="Maximum in a single purchase" value={legUsd} set={setLegUsd} unit="USDC"
                 note="Bounds one buy. It does not bound a sell." />
          <Field label="Maximum movement per leg" value={ratePct} set={setRatePct} unit="% of target"
                 note="In shares, in either direction. The only limit that bounds a sell, and why one oversized leg cannot empty a position." />
          <Field label="Drift tolerance" value={driftPct} set={setDriftPct} unit="%"
                 note="Below this the agent does nothing." />
          <Field label="Expiry" value={days} set={setDays} unit="days"
                 note="After this the mandate cannot execute again by any path." />
          <Nav next={() => setStep("review")} disabled={false} label="review" />
        </>
      )}

      {step === "review" && (
        <>
          <div style={{ border: "1px solid var(--cyan)", padding: 18, marginBottom: 18 }}>
            <p style={{ fontSize: 15, margin: "0 0 10px", lineHeight: 1.5 }}>
              You are approving the contract at{" "}
              <span className="mono">{addr(VECTRA_ADDRESS)}</span> to spend up to{" "}
              <span className="mono">${capUsd}</span> of your USDC.
            </p>
            <p style={{ fontSize: 15, margin: 0, lineHeight: 1.5 }}>
              <strong className="cyan">The cap is not a budget, it is the loss bound.</strong>{" "}
              <span className="dim">
                The contract cannot hold funds between transactions — it pulls what a
                leg needs, swaps, and sends the output to you in the same
                transaction. If it were completely broken, ${capUsd} is the most
                you could lose.
              </span>
            </p>
          </div>
          <p className="dim" style={{ fontSize: 13, margin: "0 0 16px" }}>
            This is <strong style={{ color: "var(--bone)" }}>two transactions</strong>: the
            allowance, then the mandate. If you reject the second, the allowance
            remains and this page will offer to revoke it.
          </p>
          {err && <p className="red mono" style={{ fontSize: 12, wordBreak: "break-all" }}>{err}</p>}
          <button className="btn btn-primary" disabled={!!busy} onClick={() => void submit()}>
            {busy ?? "Approve and create"}
          </button>
        </>
      )}
    </section>
  );
}

function Nav({ next, disabled, label }: { next: () => void; disabled: boolean; label: string }) {
  return (
    <div style={{ marginTop: 18 }}>
      <button className="btn btn-primary" onClick={next} disabled={disabled}>{label}</button>
    </div>
  );
}

function Field({ label, value, set, unit, note }: {
  label: string; value: string; set: (v: string) => void; unit: string; note: string;
}) {
  return (
    <div style={{ padding: "12px 0", borderTop: "1px solid var(--bone-12)" }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center" }}>
        <span style={{ fontSize: 14 }}>{label}</span>
        <span style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <input
            className="mono" value={value} onChange={(e) => set(e.target.value)} inputMode="decimal"
            style={{ background: "transparent", border: "1px solid var(--bone-30)", color: "var(--bone)", padding: "6px 10px", width: 90, fontSize: 13, textAlign: "right" }}
          />
          <span className="faint mono" style={{ fontSize: 12, minWidth: 74 }}>{unit}</span>
        </span>
      </div>
      <p className="dim" style={{ fontSize: 12, margin: "6px 0 0", maxWidth: 620 }}>{note}</p>
    </div>
  );
}


