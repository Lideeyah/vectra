"""Fetch a swap payload and hand it straight to the caller. No file, no commit.

A payload carries a deadline the router enforces, so its useful life is minutes.
Routing one through a commit, a notification and a human before it is used gives
it four chances to go stale. This exists so the fetch and the use happen in one
process: it prints the calldata to stdout, and the fork test consumes it in the
same job.

Read-only. Requests a payload and prints it; signs nothing, sends nothing.
"""

import json
import os
import sys
import time

import okx_dex

USDC = "0xb6ceceab302e2e4948951ee7843fc24e92933061"
NVDAX = "0xc845b2894dbddd03858fd2d643b4ef725fe0849d"
USDC_DECIMALS = 6


def fetch(wallet, token=NVDAX, usd=5.0, slippage="0.5"):
    amount = int(round(usd * 10 ** USDC_DECIMALS))
    status, body, _ = okx_dex.endpoint("swap", {
        "amount": str(amount),
        "fromTokenAddress": USDC,
        "toTokenAddress": token,
        "slippagePercent": slippage,
        "userWalletAddress": wallet,
    })
    if not (isinstance(body, dict) and body.get("code") in ("0", 0) and body.get("data")):
        atts = (body.get("attempts") if isinstance(body, dict) else None) or []
        detail = "; ".join(f"{a['path']} code={a['code']} {a['msg'][:80]}" for a in atts)
        raise SystemExit(f"swap payload refused: {detail or str(body)[:200]}")

    d = body["data"][0] if isinstance(body["data"], list) else body["data"]
    tx = d.get("tx") or {}
    return {
        "wallet": wallet,
        "to": tx.get("to"),
        "data": tx.get("data"),
        "gas": tx.get("gas"),
        "minReceiveAmount": tx.get("minReceiveAmount"),
        "amountIn": str(amount),
        "token": token,
    }


def main():
    wallet = os.environ.get("VECTRA_WALLET")
    if not wallet:
        raise SystemExit("VECTRA_WALLET is required (the address the payload is built for)")

    p = fetch(wallet, os.environ.get("VECTRA_TOKEN") or NVDAX)

    # Anything a shell will `eval` or read into env, on stdout. Diagnostics go
    # to stderr so they cannot contaminate it.
    print(f"VECTRA_PAYLOAD={p['data']}")
    print(f"VECTRA_PAYLOAD_TO={p['to']}")
    print(f"VECTRA_PAYLOAD_MINOUT={p['minReceiveAmount']}")
    print(f"VECTRA_PAYLOAD_AMOUNTIN={p['amountIn']}")
    print(f"VECTRA_PAYLOAD_TOKEN={p['token']}")
    # Wall-clock time the payload was issued. A fork pinned to a past block
    # carries that block's timestamp, which can sit behind the deadline the
    # router just issued against wall time — so the test warps to this before
    # forwarding. Without it, an expiry revert would be an artefact of the
    # fork's clock rather than a property of the router.
    print(f"VECTRA_FETCH_TIME={int(time.time())}")

    print(json.dumps({k: (v[:80] + "..." if k == "data" and v else v)
                      for k, v in p.items()}, indent=2), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
