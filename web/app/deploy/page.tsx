"use client";

import { useState } from "react";
import { encodeAbiParameters, getContractAddress, keccak256, type Address, type Hash } from "viem";
import { VECTRA_CREATION_BYTECODE } from "@/lib/bytecode.generated";
import { CHAIN, ROUTER, SPENDER, USDC, VECTRA_ADDRESS } from "@/lib/config";
import { connect, injected, publicClient, switchToXLayer, walletState, xlayer } from "@/lib/chain";
import { createWalletClient, custom } from "viem";

/**
 * Deploy the contract from the browser wallet.
 *
 * This exists because the deployer key is in a wallet that cannot export it,
 * so `forge create` has nothing to sign with. The wallet signs instead and the
 * key never leaves it.
 *
 * What makes this equivalent to a forge deploy rather than a different build:
 * the bytes come from lib/bytecode.generated.ts, generated from the SAME
 * compiled artifact, and the page checks the deployed runtime hash against the
 * recorded one after the transaction lands. If they differ, the deployment is
 * not the audited contract and the page says so.
 */
const EXPECTED_RUNTIME_HASH =
  "0xc20f87eccd8af42fa47608d1c60b4cce916df43dce508670876ab6a8c6479db9";

export default function Deploy() {
  const [log, setLog] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const say = (s: string) => setLog((l) => [...l, s]);

  const run = async () => {
    setLog([]);
    setBusy(true);
    try {
      const w = await walletState();
      if (w.kind === "none") throw new Error("no wallet extension detected");
      if (w.kind === "locked") await connect();

      const st = await walletState();
      if (st.kind !== "ready") throw new Error("wallet not ready");
      const from = st.address as Address;
      say(`account ${from}`);

      if (st.chainId !== CHAIN.id) {
        throw new Error(
          `wallet is on chain ${st.chainId}, not X Layer (${CHAIN.id}). Switch and retry.`,
        );
      }

      // The predicted address depends on the deployer AND its nonce, so both
      // are checked before anything is signed rather than explained after.
      const nonce = await publicClient.getTransactionCount({ address: from });
      say(`nonce ${nonce}`);
      const predicted = getContractAddress({ from, nonce: BigInt(nonce) });
      say(`this deploy would land at ${predicted}`);
      if (predicted.toLowerCase() !== VECTRA_ADDRESS.toLowerCase()) {
        throw new Error(
          `that is NOT the configured address ${VECTRA_ADDRESS}. ` +
            `Wrong account, or the nonce has moved. Nothing signed.`,
        );
      }

      const args = encodeAbiParameters(
        [{ type: "address" }, { type: "address" }, { type: "address" }],
        [ROUTER, SPENDER, USDC],
      );
      const data = (VECTRA_CREATION_BYTECODE + args.slice(2)) as `0x${string}`;
      say(`sending ${(data.length / 2 - 1).toLocaleString()} bytes — confirm in your wallet`);

      const wallet = createWalletClient({
        account: from,
        chain: xlayer,
        transport: custom(injected() as never),
      });
      const hash: Hash = await wallet.sendTransaction({ data });
      say(`tx ${hash}`);

      const rcpt = await publicClient.waitForTransactionReceipt({ hash });
      say(`status ${rcpt.status}, gas used ${rcpt.gasUsed}`);
      if (rcpt.status !== "success") throw new Error("deployment reverted");

      const addr = rcpt.contractAddress as Address;
      say(`deployed at ${addr}`);

      // The claim, checked. Code at the address must be the audited build.
      const code = await publicClient.getBytecode({ address: addr });
      if (!code) throw new Error("no code at the deployed address");
      const h = keccak256(code);
      say(`runtime keccak ${h}`);
      say(
        h === EXPECTED_RUNTIME_HASH
          ? "MATCHES the recorded deployment hash — this is the audited build"
          : `DOES NOT MATCH ${EXPECTED_RUNTIME_HASH} — do not use this deployment`,
      );
    } catch (e) {
      say(`ERROR: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="wrap" style={{ paddingTop: 48, paddingBottom: 80 }}>
      <h1 style={{ fontSize: 20, fontWeight: 500 }}>Deploy VectraMandate</h1>
      <p className="dim" style={{ fontSize: 13, maxWidth: 640 }}>
        Signs with your wallet extension. The bytes are the compiled deployment
        artifact, and the runtime hash is checked against the recorded one after
        it lands. Nothing is signed unless the resulting address matches{" "}
        <span className="mono">{VECTRA_ADDRESS}</span>.
      </p>

      <div style={{ display: "flex", gap: 10, marginTop: 16, flexWrap: "wrap" }}>
        <button
          className="btn"
          disabled={busy}
          onClick={async () => {
            try {
              await switchToXLayer();
              say(`switched to ${CHAIN.name}`);
            } catch (e) {
              say(`switch failed: ${e instanceof Error ? e.message : String(e)}`);
            }
          }}
        >
          Switch to {CHAIN.name}
        </button>
        <button className="btn" onClick={run} disabled={busy}>
          {busy ? "deploying…" : "Deploy"}
        </button>
      </div>

      {log.length > 0 && (
        <pre className="mono" style={{ fontSize: 12, marginTop: 20, whiteSpace: "pre-wrap", wordBreak: "break-all" }}>
          {log.join("\n")}
        </pre>
      )}
    </div>
  );
}
