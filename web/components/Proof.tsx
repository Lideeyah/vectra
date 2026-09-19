"use client";

import { CHAIN, ROUTER, SPENDER, USDC, VECTRA_ADDRESS, explorerAddress } from "@/lib/config";

/**
 * Proof is not a page, it is a property of every number. This is the index of
 * where things come from, so any figure on screen can be re-derived by someone
 * who does not trust this site.
 */
export function Proof({ deployed, dataBase }: { deployed: boolean; dataBase: string }) {
  return (
    <section style={{ marginTop: 64, paddingTop: 24, borderTop: "1px solid var(--bone-12)" }}>
      <div className="dim" style={{ fontSize: 12, letterSpacing: "0.08em", marginBottom: 14 }}>
        WHERE EVERY NUMBER COMES FROM
      </div>

      <p className="dim" style={{ fontSize: 13, margin: "0 0 18px", maxWidth: 640 }}>
        Nothing here is stored by this site. Every figure is a contract read you
        can repeat, a transaction you can open on the explorer, or a recorded
        observation with its timestamp. There is no database.
      </p>

      <Row label="Contract" value={VECTRA_ADDRESS} href={explorerAddress(VECTRA_ADDRESS)}
           note={deployed ? "holds code" : "no code at this address yet"} />
      <Row label="Router (call target)" value={ROUTER} href={explorerAddress(ROUTER)}
           note="verified against a live swap payload" />
      <Row label="Spender (allowance target)" value={SPENDER} href={explorerAddress(SPENDER)}
           note="differs from the router — approving the wrong one reverts every swap" />
      <Row label="USDC" value={USDC} href={explorerAddress(USDC)} note="6 decimals; the accounting unit" />
      <Row label="Recorder & agent output" value={dataBase} href={dataBase}
           note="committed to the repository, timestamped, append-only" />
      <Row label="Chain" value={`${CHAIN.name} · ${CHAIN.id}`} href={CHAIN.explorer} note="" />
    </section>
  );
}

function Row({ label, value, href, note }: { label: string; value: string; href: string; note: string }) {
  return (
    <div style={{ padding: "10px 0", borderTop: "1px solid var(--bone-12)" }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 16, flexWrap: "wrap" }}>
        <span style={{ fontSize: 13 }}>{label}</span>
        <a className="mono" style={{ fontSize: 12, wordBreak: "break-all" }} href={href} target="_blank" rel="noreferrer">
          {value}
        </a>
      </div>
      {note && <div className="faint" style={{ fontSize: 12, marginTop: 4 }}>{note}</div>}
    </div>
  );
}
