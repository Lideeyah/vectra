"""Verify the aggregator's swap endpoint shape on X Layer. Read-only.

Answers three of the SPEC section 13 verifications, all of which gate the contract:

  1. The OKX DEX aggregator router address on X Layer (the call target the
     contract forwards to, and the spender an allowance must be granted to).
  2. The exact calldata shape the swap endpoint returns, since the contract
     forwards it verbatim as routerCalldata.
  3. Whether the swap endpoint permits a recipient other than the caller, which
     decides whether output can be sent straight to the user or must pass
     through the contract.

This requests transaction payloads and prints them. It never signs, never
broadcasts, and holds no private key. Nothing here can move funds.
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import okx_dex

USDC = "0xb6ceceab302e2e4948951ee7843fc24e92933061"
NVDAX = "0xc845b2894dbddd03858fd2d643b4ef725fe0849d"

WALLET = os.environ.get("VECTRA_WALLET", "0x2f45e637920cc7c7be15130ab49224c989572ad8")
# A distinct address used only to test whether the router will direct output
# somewhere other than the caller. Never funded, never transacted with.
PROBE_RECIPIENT = "0x1111111111111111111111111111111111111111"

AMOUNT_USD = 5.0
USDC_DECIMALS = 6
SLIPPAGE = "0.01"

OUT = Path("data/verifications/swap.json")


def candidates():
    """Tokens to try, most-likely-liquid first."""
    env = os.environ.get("VECTRA_TOKEN")
    if env:
        yield ("env", env)

    cons = Path("data/constituents.json")
    if cons.exists():
        try:
            for c in json.loads(cons.read_text()).get("constituents", []):
                yield (c.get("symbol", "?"), c["address"])
        except (json.JSONDecodeError, KeyError):
            pass

    probe = Path("data/liquidity_probe.json")
    if probe.exists():
        try:
            entries = [e for e in json.loads(probe.read_text()).values()
                       if e.get("quotable")]
            for e in entries:
                yield (e.get("symbol", "?"), e["address"])
        except (json.JSONDecodeError, KeyError):
            pass

    yield ("NVDAx", NVDAX)


def call(path, params):
    status, body = okx_dex.request(path, params)
    ok = isinstance(body, dict) and body.get("code") in ("0", 0) and body.get("data")
    return ok, status, body


def approve_spender(token):
    """The address an ERC-20 allowance must be granted to."""
    for path in ("/api/v5/dex/aggregator/approve-transaction",
                 "/api/v6/dex/aggregator/approve-transaction"):
        params = {"chainId": okx_dex.X_LAYER, "tokenContractAddress": token,
                  "approveAmount": str(int(AMOUNT_USD * 10 ** USDC_DECIMALS))}
        if "v6" in path:
            params["chainIndex"] = params.pop("chainId")
        ok, status, body = call(path, params)
        if ok:
            d = body["data"][0] if isinstance(body["data"], list) else body["data"]
            return {"endpoint": path, "spender": d.get("dexContractAddress"), "raw": d}
        last = {"endpoint": path, "httpStatus": status, "error": body}
    return last


def swap(token, receiver=None):
    amount = str(int(AMOUNT_USD * 10 ** USDC_DECIMALS))
    params = {
        "chainId": okx_dex.X_LAYER,
        "amount": amount,
        "fromTokenAddress": USDC,
        "toTokenAddress": token,
        "slippage": SLIPPAGE,
        "userWalletAddress": WALLET,
    }
    if receiver:
        params["swapReceiverAddress"] = receiver
    ok, status, body = call("/api/v5/dex/aggregator/swap", params)
    if not ok:
        p6 = dict(params)
        p6["chainIndex"] = p6.pop("chainId")
        ok, status, body = call("/api/v6/dex/aggregator/swap", p6)
    return ok, status, body


def summarise(body):
    d = body["data"][0] if isinstance(body["data"], list) else body["data"]
    tx = d.get("tx") or {}
    data = tx.get("data") or ""
    return {
        "router_to": tx.get("to"),
        "from": tx.get("from"),
        "value": tx.get("value"),
        "gas": tx.get("gas"),
        "gasPrice": tx.get("gasPrice"),
        "minReceiveAmount": tx.get("minReceiveAmount"),
        "calldata_selector": data[:10] if data else None,
        "calldata_len_bytes": (len(data) - 2) // 2 if data.startswith("0x") else None,
        "calldata_head": data[:266],
        "calldata_full": data,
        "routerResult": d.get("routerResult", {}).get("dexRouterList") if isinstance(d.get("routerResult"), dict) else None,
    }


def main():
    print("Swap endpoint verification — X Layer, read-only, no transaction is sent.\n")
    print(f"wallet         {WALLET}")
    print(f"probe receiver {PROBE_RECIPIENT}")
    print(f"notional       ${AMOUNT_USD:g} USDC\n")

    chosen = None
    tried = []
    for sym, addr in candidates():
        if addr.lower() in [t[1].lower() for t in tried]:
            continue
        tried.append((sym, addr))
        print(f"trying {sym} {addr} ...")
        ok, status, body = swap(addr)
        if ok:
            chosen = (sym, addr, body)
            print(f"  swap payload returned for {sym}\n")
            break
        msg = body.get("msg") if isinstance(body, dict) else str(body)[:200]
        code = body.get("code") if isinstance(body, dict) else "?"
        print(f"  no payload (http={status} code={code} msg={msg})")
        if len(tried) >= 8:
            break

    if not chosen:
        print("\nFAILED: no token returned a swap payload.", file=sys.stderr)
        print("Tried: " + ", ".join(s for s, _ in tried), file=sys.stderr)
        return 1

    sym, addr, body = chosen
    base = summarise(body)

    print("=" * 68)
    print(f"1. ROUTER ADDRESS  (verification 13.2)")
    print("=" * 68)
    print(f"  swap tx.to        {base['router_to']}")
    spender = approve_spender(USDC)
    print(f"  approve spender   {spender.get('spender')}")
    if spender.get("spender") and base["router_to"]:
        same = spender["spender"].lower() == base["router_to"].lower()
        print(f"  same address?     {same}")
        if not same:
            print("  NOTE: allowance target differs from the call target. The contract")
            print("        must approve the spender, not the router it calls.")

    print("\n" + "=" * 68)
    print("2. CALLDATA SHAPE  (verification 13.3)")
    print("=" * 68)
    print(f"  selector          {base['calldata_selector']}")
    print(f"  length            {base['calldata_len_bytes']} bytes")
    print(f"  tx.value          {base['value']}")
    print(f"  gas               {base['gas']}")
    print(f"  minReceiveAmount  {base['minReceiveAmount']}")
    print(f"  head              {base['calldata_head'][:130]}...")

    print("\n" + "=" * 68)
    print("3. ALTERNATE RECIPIENT  (verification 13.4)")
    print("=" * 68)
    ok2, status2, body2 = swap(addr, receiver=PROBE_RECIPIENT)
    recipient = {"supported": False}
    if not ok2:
        msg = body2.get("msg") if isinstance(body2, dict) else str(body2)[:200]
        code = body2.get("code") if isinstance(body2, dict) else "?"
        print(f"  REJECTED (http={status2} code={code} msg={msg})")
        print("  => output cannot be redirected; it must land on the caller and be")
        print("     forwarded by the contract in the same transaction.")
        recipient.update({"httpStatus": status2, "error": body2})
    else:
        alt = summarise(body2)
        encoded = PROBE_RECIPIENT[2:].lower() in (alt["calldata_full"] or "").lower()
        differs = alt["calldata_full"] != base["calldata_full"]
        print(f"  accepted          True")
        print(f"  calldata differs  {differs}")
        print(f"  receiver encoded  {encoded}")
        if encoded:
            print("  => SUPPORTED. Output can be sent straight to the mandate owner,")
            print("     so the contract need never hold the token at all.")
        else:
            print("  => accepted but the address is NOT in the calldata. Treat as")
            print("     unsupported: the parameter was ignored.")
        recipient.update({"supported": bool(encoded), "calldataDiffers": differs,
                          "alt": alt})

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "verifiedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "chain": okx_dex.X_LAYER,
        "token": {"symbol": sym, "address": addr},
        "notionalUsd": AMOUNT_USD,
        "wallet": WALLET,
        "router": {"txTo": base["router_to"], "approveSpender": spender.get("spender"),
                   "approveRaw": spender},
        "calldata": base,
        "alternateRecipient": recipient,
    }, indent=2) + "\n")
    print(f"\nwritten to {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
