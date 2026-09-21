"use client";

import { useEffect, useState } from "react";
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

  /**
   * Pick the wallet explicitly instead of taking window.ethereum.
   *
   * Two extensions are installed and OKX Wallet claims window.ethereum, so the
   * page never saw MetaMask at all — and the wallet that owns that property is
   * exactly the one that cannot deploy. EIP-6963 asks every installed wallet to
   * announce itself, which both of these support.
   */
  const [wallets, setWallets] = useState<{ name: string; provider: unknown }[]>([]);
  const [picked, setPicked] = useState<{ name: string; provider: unknown } | null>(null);

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

  /** The chosen wallet, or whatever claimed window.ethereum as a fallback. */
  const eth = () => (picked?.provider ?? injected()) as Eth;

  type Eth = { request: (a: { method: string; params?: unknown[] }) => Promise<unknown> };

  const state = async () => {
    const e = eth();
    if (!e) throw new Error("no wallet selected");
    let accounts = (await e.request({ method: "eth_accounts" })) as string[];
    if (!accounts?.length) {
      accounts = (await e.request({ method: "eth_requestAccounts" })) as string[];
    }
    const chainIdHex = (await e.request({ method: "eth_chainId" })) as string;
    return { address: accounts[0] as Address, chainId: Number(chainIdHex) };
  };

  const run = async () => {
    setLog([]);
    setBusy(true);
    try {
      if (!picked) throw new Error("choose a wallet first");
      const st = await state();
      const from = st.address;
      say(`wallet ${picked.name}, account ${from}`);

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
        transport: custom(eth() as never),
      });
      // Estimate with OUR rpc and pass gas explicitly. Left to itself the
      // wallet estimates a contract creation through its own node, and a
      // failure there surfaces as an opaque signing error rather than as the
      // estimation problem it actually is.
      let gas: bigint;
      try {
        gas = await publicClient.estimateGas({ account: from, data });
        say(`estimated gas ${gas}`);
      } catch (e) {
        throw new Error(
          `gas estimation failed on ${CHAIN.rpc}: ` +
            (e instanceof Error ? e.message : String(e)),
        );
      }
      const gasPrice = await publicClient.getGasPrice();
      const cost = gas * gasPrice;
      const bal = await publicClient.getBalance({ address: from });
      say(`gas price ${gasPrice} wei, cost ~${cost} wei, balance ${bal} wei`);
      if (bal < cost) throw new Error(`not enough OKB: need ${cost}, have ${bal}`);

      // LEGACY, not EIP-1559. viem defaults to a type-2 transaction with
      // maxFeePerGas/maxPriorityFeePerGas. X Layer is a zkEVM and reports a
      // legacy gas price; a wallet that cannot compute a 1559 fee here shows
      // the fee as "Free" and then fails internally, which it reports back as
      // a user rejection (4001) rather than as the fee problem it is.
      const hash: Hash = await wallet.sendTransaction({
        data,
        gas: (gas * 12n) / 10n,
        gasPrice: (gasPrice * 12n) / 10n,
        type: "legacy",
      });
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
      // The whole error, not its first line. A wallet's useful detail is
      // usually below the headline.
      const msg = e instanceof Error ? (e.stack ?? e.message) : String(e);
      say(`ERROR: ${msg}`);
      console.error(e);
    } finally {
      setBusy(false);
    }
  };

  /**
   * Isolate the failure. This is an ordinary transfer — it HAS a `to`, moves
   * zero value, and costs ~21000 gas. If the wallet signs this but not the
   * deployment, the blocker is contract creation specifically, which is a
   * known limitation of some MPC signers. If it fails too, the wallet cannot
   * sign on this chain at all. Either answer ends the guessing.
   */
  const testSign = async () => {
    setLog([]);
    setBusy(true);
    try {
      if (!picked) throw new Error("choose a wallet first");
      const s2 = await state();
      const from = s2.address;
      if (s2.chainId !== CHAIN.id) throw new Error(`wrong chain ${s2.chainId}`);

      const gasPrice = await publicClient.getGasPrice();
      say(`test: sending 0 value to yourself, 21000 gas @ ${gasPrice} wei`);

      const w = createWalletClient({
        account: from, chain: xlayer, transport: custom(eth() as never),
      });
      const hash = await w.sendTransaction({
        to: from, value: 0n, gas: 21000n,
        gasPrice: (gasPrice * 12n) / 10n, type: "legacy",
      });
      say(`SIGNED. tx ${hash}`);
      const r = await publicClient.waitForTransactionReceipt({ hash });
      say(`status ${r.status}`);
      say("=> the wallet CAN sign. The blocker is contract creation specifically.");
    } catch (e) {
      say(`test failed: ${e instanceof Error ? e.message : String(e)}`);
      say("=> the wallet cannot sign a plain transfer either.");
      console.error(e);
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

      <div style={{ marginTop: 20 }}>
        <div className="dim" style={{ fontSize: 12, marginBottom: 8 }}>
          WALLET {picked ? `— using ${picked.name}` : "— choose one"}
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {wallets.length === 0 && (
            <span className="faint" style={{ fontSize: 12 }}>no wallets announced</span>
          )}
          {wallets.map((w) => (
            <button
              key={w.name}
              className="btn"
              onClick={() => { setPicked(w); setLog([`selected ${w.name}`]); }}
              style={picked?.name === w.name ? { borderColor: "var(--cyan)", color: "var(--cyan)" } : undefined}
            >
              {w.name}
            </button>
          ))}
        </div>
      </div>

      <div style={{ display: "flex", gap: 10, marginTop: 16, flexWrap: "wrap" }}>
        <button
          className="btn"
          disabled={busy}
          onClick={async () => {
            try {
              const e = eth();
              const hexId = `0x${CHAIN.id.toString(16)}`;
              try {
                await e.request({ method: "wallet_switchEthereumChain", params: [{ chainId: hexId }] });
              } catch {
                await e.request({ method: "wallet_addEthereumChain", params: [{
                  chainId: hexId, chainName: CHAIN.name,
                  nativeCurrency: CHAIN.currency,
                  rpcUrls: [CHAIN.rpc], blockExplorerUrls: [CHAIN.explorer],
                }] });
              }
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
        <button className="btn" onClick={testSign} disabled={busy}>
          Test sign
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
