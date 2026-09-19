"""Quote one token across a ladder of sizes and print the rate and route at each.

Purpose: MSTRx measured a NEGATIVE depth — a better rate at $50 than at $1. The
product's central claim is that cost is proportional at any size, so an asset
that prices better when larger is either a routing artifact (harmless once
named) or evidence that small size carries a penalty on some assets (in which
case the claim needs qualifying). Those have different consequences, and the
route source at each size is what distinguishes them.

A control asset is quoted alongside so the comparison is against something
known-good rather than against theory.

Read-only. Quotes only; nothing is signed or sent.
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import okx_dex

USDC = "0xb6ceceab302e2e4948951ee7843fc24e92933061"
USDC_DECIMALS = 6
LADDER = [1.0, 5.0, 10.0, 25.0, 50.0, 100.0]
THROTTLE_S = 3.0
OUT = Path("data/verifications/depth_curve.json")

# Subject and control. MSTRx is the anomaly; SPYx measured the cleanest depth
# in the set (0.0002%) and stands in for "known good".
DEFAULT_TOKENS = {
    "MSTRx": "0xae2f842ef90c0d5213259ab82639d5bbf649b08e",
    "SPYx": "0x90a2a4c76b5d8c0bc892a69ea28aa775a8f2dd48",
}


def quote_at(addr, usd, decimals=18):
    amount = int(round(usd * 10 ** USDC_DECIMALS))
    status, body = okx_dex.quote(USDC, addr, amount)
    if not (isinstance(body, dict) and body.get("code") in ("0", 0) and body.get("data")):
        atts = (body.get("attempts") if isinstance(body, dict) else None) or []
        msg = atts[0].get("msg") if atts else str(body)[:120]
        return {"usd": usd, "ok": False, "error": msg}
    d = body["data"][0] if isinstance(body["data"], list) else body["data"]
    try:
        out = int(d.get("toTokenAmount") or 0)
    except (TypeError, ValueError):
        out = 0
    if out <= 0:
        return {"usd": usd, "ok": False, "error": "zero output"}
    tokens = out / 10 ** decimals
    return {
        "usd": usd, "ok": True,
        "tokensOut": tokens,
        "rate": tokens / usd,          # tokens per USDC — higher is better
        "unitPriceUsd": usd / tokens,  # USD per token — lower is better
        "routes": okx_dex.routes_of(d),
    }


def run(symbol, addr):
    print(f"\n{'=' * 72}\n{symbol}  {addr}\n{'=' * 72}")
    print(f"{'SIZE':>8} {'TOKENS OUT':>16} {'RATE (tok/$)':>16} "
          f"{'$/TOKEN':>12} {'vs $1':>9}  ROUTE")
    rows, base = [], None
    for usd in LADDER:
        r = quote_at(addr, usd)
        rows.append(r)
        if not r["ok"]:
            print(f"{usd:>7.0f}$ {'—':>16} {'—':>16} {'—':>12} {'—':>9}  "
                  f"FAILED {r['error'][:40]}")
            time.sleep(THROTTLE_S)
            continue
        if base is None:
            base = r["rate"]
        delta = (r["rate"] - base) / base * 100
        route = " | ".join(r["routes"]) or "—"
        print(f"{usd:>7.0f}$ {r['tokensOut']:>16.8f} {r['rate']:>16.8f} "
              f"{r['unitPriceUsd']:>12.4f} {delta:>+8.4f}%  {route[:44]}")
        time.sleep(THROTTLE_S)

    ok = [r for r in rows if r["ok"]]
    verdict = None
    if len(ok) >= 2:
        routes = {" | ".join(r["routes"]) for r in ok}
        best = max(ok, key=lambda r: r["rate"])
        worst = min(ok, key=lambda r: r["rate"])
        spread = (best["rate"] - worst["rate"]) / worst["rate"] * 100
        improves = best["usd"] > ok[0]["usd"] and best["rate"] > ok[0]["rate"]

        print(f"\n  distinct routes across the ladder: {len(routes)}")
        for rt in sorted(routes):
            sizes = [f"${r['usd']:g}" for r in ok if " | ".join(r["routes"]) == rt]
            print(f"    {rt[:60]:<60} at {', '.join(sizes)}")
        print(f"  best rate at ${best['usd']:g}, worst at ${worst['usd']:g}, "
              f"spread {spread:.4f}%")

        if improves and len(routes) > 1:
            verdict = ("ROUTING ARTIFACT: the rate improves with size AND the "
                       "route changes, so the aggregator finds a different path "
                       "at larger size. Harmless once named.")
        elif improves:
            verdict = ("REAL SMALL-SIZE PENALTY: the rate improves with size on "
                       "a SINGLE unchanged route. Small size carries a genuine "
                       "cost here, and the proportionality claim needs "
                       "qualifying to the liquid set with exceptions.")
        else:
            verdict = ("NORMAL: the rate does not improve with size; cost is "
                       "flat or degrades as expected.")
        print(f"\n  VERDICT: {verdict}")
    return {"symbol": symbol, "address": addr, "rows": rows, "verdict": verdict}


def main():
    tokens = dict(DEFAULT_TOKENS)
    env = os.environ.get("VECTRA_TOKENS")
    if env:
        tokens = dict(pair.split("=", 1) for pair in env.split(",") if "=" in pair)

    print("Depth curve — read-only, quotes only, nothing is sent.")
    print(f"ladder: {', '.join(f'${u:g}' for u in LADDER)}")

    results = [run(sym, addr) for sym, addr in tokens.items()]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "ladderUsd": LADDER, "results": results,
    }, indent=2) + "\n")
    print(f"\nwritten to {OUT}")
    return 0 if any(r["verdict"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
