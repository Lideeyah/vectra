"""Discover the xStock universe on X Layer and fix the recording set.

Run once. The constituent set is evidence: it is written to data/constituents.json
and committed, so the series is measured against a fixed basket rather than one
that drifts as the aggregator's listings change.

Selection basis is liquidity, measured as observed price impact on a real $5
quote — not name recognition. NVDAx is pinned in regardless, since it is the
asset the section 2 cost reading was taken on.
"""

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import okx_dex
import xlayer

USDC = "0xb6ceceab302e2e4948951ee7843fc24e92933061"
NVDAX = "0xc845b2894dbddd03858fd2d643b4ef725fe0849d"
PROBE_USD = 5.0
MIN_SET = 10
THROTTLE_S = 1.1

OUT = Path("data/constituents.json")


def is_xstock(t):
    sym = t.get("tokenSymbol") or ""
    name = (t.get("tokenName") or "").lower()
    if "xstock" in name or "backed" in name:
        return True
    core = sym[:-1]
    return len(sym) > 1 and sym.endswith("x") and core.isalpha() and core.isupper()


def decimals_of(t, default=18):
    for k in ("decimals", "decimal"):
        if t.get(k) not in (None, ""):
            return int(t[k])
    return default


def main():
    tokens, attempts = okx_dex.all_tokens()
    if tokens is None:
        print("DISCOVERY FAILED — token list unreachable.", file=sys.stderr)
        for path, status, body in attempts:
            print(f"  {path} HTTP {status}: {json.dumps(body)[:400] if not isinstance(body, str) else body[:400]}",
                  file=sys.stderr)
        return 1

    by_addr = {(t.get("tokenContractAddress") or "").lower(): t for t in tokens}
    usdc = by_addr.get(USDC.lower()) or {
        "tokenSymbol": "USDC", "tokenContractAddress": USDC, "decimals": 6}
    stocks = [t for t in tokens if is_xstock(t)]

    print(f"chain 196: {len(tokens)} tokens total, {len(stocks)} xStock candidates\n")
    print(f"{'SYMBOL':<10} {'DEC':<4} {'ADDRESS':<44} NAME")
    for t in sorted(stocks, key=lambda x: x.get("tokenSymbol") or ""):
        print(f"{t.get('tokenSymbol',''):<10} {decimals_of(t):<4} "
              f"{t.get('tokenContractAddress',''):<44} {t.get('tokenName','')}")

    if len(stocks) < MIN_SET:
        print(f"\nNOTE: only {len(stocks)} xStocks exist on X Layer, fewer than the "
              f"{MIN_SET} requested. Recording every one that exists.")

    # Rank by observed liquidity at a real $5 quote.
    print(f"\nProbing liquidity at ${PROBE_USD:g} per asset...\n")
    dec_in = decimals_of(usdc, 6)
    amount = int(round(PROBE_USD * 10 ** dec_in))
    ranked = []
    for t in stocks:
        addr = t["tokenContractAddress"]
        status, body = okx_dex.quote(USDC, addr, amount)
        entry = {"token": t, "decimals": decimals_of(t)}
        if isinstance(body, dict) and body.get("code") in ("0", 0) and body.get("data"):
            d = body["data"][0] if isinstance(body["data"], list) else body["data"]
            try:
                impact = abs(float(d.get("priceImpactPercentage")))
            except (TypeError, ValueError):
                impact = None
            out_units = int(d.get("toTokenAmount") or 0)
            entry.update({
                "quotable": out_units > 0,
                "priceImpactPct": impact,
                "amountOutUnits": str(out_units),
                "routes": okx_dex.routes_of(d),
            })
        else:
            entry.update({"quotable": False, "priceImpactPct": None,
                          "error": body if isinstance(body, (dict, str)) else str(body)})
        mult, mult_raw = xlayer.multiplier(addr)
        entry["multiplier"] = mult
        entry["multiplierRaw"] = str(mult_raw) if mult_raw is not None else None
        ranked.append(entry)
        sym = t.get("tokenSymbol")
        print(f"  {sym:<10} quotable={entry['quotable']!s:<5} "
              f"impact={entry['priceImpactPct']} multiplier={mult}")
        time.sleep(THROTTLE_S)

    quotable = [e for e in ranked if e["quotable"]]
    quotable.sort(key=lambda e: (e["priceImpactPct"] is None, e["priceImpactPct"] or 0))

    chosen, seen = [], set()
    for e in quotable:
        addr = e["token"]["tokenContractAddress"].lower()
        if addr == NVDAX.lower():
            continue
        chosen.append(e)
        seen.add(addr)
        if len(chosen) >= max(MIN_SET, 0) + 4:
            break

    nvdax = next((e for e in ranked if e["token"]["tokenContractAddress"].lower() == NVDAX.lower()), None)
    if nvdax and nvdax["quotable"]:
        chosen.insert(0, nvdax)

    payload = {
        "fixedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "chain": okx_dex.X_LAYER,
        "probeNotionalUsd": PROBE_USD,
        "selectionBasis": "lowest observed price impact on a live $5 USDC quote; NVDAx pinned",
        "usdc": {"symbol": usdc.get("tokenSymbol"), "address": usdc.get("tokenContractAddress"),
                 "decimals": dec_in},
        "totalTokensOnChain": len(tokens),
        "xstocksFound": len(stocks),
        "constituents": [{
            "symbol": e["token"].get("tokenSymbol"),
            "name": e["token"].get("tokenName"),
            "address": e["token"].get("tokenContractAddress"),
            "decimals": e["decimals"],
            "priceImpactPctAtProbe": e["priceImpactPct"],
            "multiplierAtFix": e["multiplier"],
        } for e in chosen],
        "rejected": [{
            "symbol": e["token"].get("tokenSymbol"),
            "address": e["token"].get("tokenContractAddress"),
            "reason": "no quote at probe size" if not e["quotable"] else "ranked below cutoff",
        } for e in ranked if e not in chosen],
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"\nFixed {len(chosen)} constituents -> {OUT}")
    for c in payload["constituents"]:
        print(f"  {c['symbol']:<10} impact={c['priceImpactPctAtProbe']} {c['address']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
