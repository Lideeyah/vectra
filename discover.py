"""Discover the xStock universe on X Layer and fix the recording set.

Three phases, each persisting its own output so a timeout never discards work:

  1. Universe      one API call -> data/xstocks_all.json
  2. Liquidity     one $5 quote per candidate -> data/liquidity_probe.json
  3. Selection     rank and fix -> data/constituents.json

X Layer lists hundreds of xStocks, so phase 2 is long. It is resumable: every
probe is cached and a re-run skips what it already has. Run it repeatedly until
it reports nothing left to probe.

Selection basis is liquidity, measured as observed price impact on a real $5
quote, not name recognition. NVDAx is pinned in regardless.
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import okx_dex
import xlayer

USDC = "0xb6ceceab302e2e4948951ee7843fc24e92933061"
NVDAX = "0xc845b2894dbddd03858fd2d643b4ef725fe0849d"
PROBE_USD = 5.0
TARGET_SET = int(os.environ.get("VECTRA_SET_SIZE", "14"))
MAX_PROBE = int(os.environ.get("VECTRA_MAX_PROBE", "0"))  # 0 = no limit
THROTTLE_S = float(os.environ.get("VECTRA_THROTTLE", "1.1"))
FLUSH_EVERY = 10

UNIVERSE = Path("data/xstocks_all.json")
PROBE = Path("data/liquidity_probe.json")
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


def load(path, default):
    if path.exists():
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            return default
    return default


def save(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n")


def phase_universe():
    tokens, attempts = okx_dex.all_tokens()
    if tokens is None:
        print("DISCOVERY FAILED — token list unreachable.", file=sys.stderr)
        for path, status, body in attempts:
            detail = json.dumps(body)[:400] if not isinstance(body, str) else body[:400]
            print(f"  {path} HTTP {status}: {detail}", file=sys.stderr)
        return None, None

    by_addr = {(t.get("tokenContractAddress") or "").lower(): t for t in tokens}
    usdc = by_addr.get(USDC.lower()) or {
        "tokenSymbol": "USDC", "tokenContractAddress": USDC, "decimals": 6}
    stocks = sorted([t for t in tokens if is_xstock(t)],
                    key=lambda x: x.get("tokenSymbol") or "")

    save(UNIVERSE, {
        "fetchedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "chain": okx_dex.X_LAYER,
        "totalTokensOnChain": len(tokens),
        "xstocksFound": len(stocks),
        "usdc": {"symbol": usdc.get("tokenSymbol"),
                 "address": usdc.get("tokenContractAddress"),
                 "decimals": decimals_of(usdc, 6)},
        "xstocks": [{"symbol": t.get("tokenSymbol"), "name": t.get("tokenName"),
                     "address": t.get("tokenContractAddress"), "decimals": decimals_of(t)}
                    for t in stocks],
    })
    print(f"chain 196: {len(tokens)} tokens, {len(stocks)} xStocks -> {UNIVERSE}")
    return usdc, stocks


def phase_probe(usdc, stocks):
    """Resumable. Returns the probe cache keyed by lowercase address."""
    cache = load(PROBE, {})
    todo = [t for t in stocks
            if (t.get("tokenContractAddress") or "").lower() not in cache]
    if MAX_PROBE:
        todo = todo[:MAX_PROBE]

    print(f"probe: {len(cache)} cached, {len(todo)} to go "
          f"(~{len(todo) * THROTTLE_S / 60:.1f} min)")

    dec_in = decimals_of(usdc, 6)
    amount = int(round(PROBE_USD * 10 ** dec_in))
    done = 0

    try:
        for t in todo:
            addr = t["tokenContractAddress"]
            key = addr.lower()
            entry = {"symbol": t.get("tokenSymbol"), "name": t.get("tokenName"),
                     "address": addr, "decimals": decimals_of(t),
                     "probedAt": datetime.now(timezone.utc).isoformat(timespec="seconds")}

            status, body = okx_dex.quote(usdc["tokenContractAddress"], addr, amount)
            if isinstance(body, dict) and body.get("code") in ("0", 0) and body.get("data"):
                d = body["data"][0] if isinstance(body["data"], list) else body["data"]
                try:
                    out_units = int(d.get("toTokenAmount") or 0)
                except (TypeError, ValueError):
                    out_units = 0
                try:
                    impact = abs(float(d.get("priceImpactPercentage")))
                except (TypeError, ValueError):
                    impact = None
                entry.update({"quotable": out_units > 0, "priceImpactPct": impact,
                              "amountOutUnits": str(out_units),
                              "routes": okx_dex.routes_of(d)})
            else:
                msg = body.get("msg") if isinstance(body, dict) else str(body)[:160]
                code = body.get("code") if isinstance(body, dict) else "?"
                entry.update({"quotable": False, "priceImpactPct": None,
                              "error": f"http={status} code={code} msg={msg}"[:200]})

            mult, mult_raw = xlayer.multiplier(addr)
            entry["multiplier"] = mult
            entry["multiplierRaw"] = str(mult_raw) if mult_raw is not None else None

            cache[key] = entry
            done += 1
            flag = "ok " if entry["quotable"] else "DEAD"
            print(f"  [{done}/{len(todo)}] {entry['symbol']:<10} {flag} "
                  f"impact={entry['priceImpactPct']} mult={mult}")

            if done % FLUSH_EVERY == 0:
                save(PROBE, cache)
            time.sleep(THROTTLE_S)
    except KeyboardInterrupt:
        print("interrupted — flushing cache", file=sys.stderr)
    finally:
        save(PROBE, cache)

    remaining = len([t for t in stocks
                     if (t.get("tokenContractAddress") or "").lower() not in cache])
    print(f"probe cache: {len(cache)} entries, {remaining} still unprobed")
    return cache, remaining


def phase_select(usdc, cache, universe_count):
    quotable = [e for e in cache.values() if e.get("quotable")]
    quotable.sort(key=lambda e: (e.get("priceImpactPct") is None,
                                 e.get("priceImpactPct") or 0))

    chosen = [e for e in quotable
              if e["address"].lower() != NVDAX.lower()][:max(TARGET_SET - 1, 0)]
    nvdax = cache.get(NVDAX.lower())
    if nvdax and nvdax.get("quotable"):
        chosen.insert(0, nvdax)
    elif nvdax:
        print("WARNING: NVDAx did not return a quote at probe size; not pinned.",
              file=sys.stderr)

    if len(chosen) < 10:
        print(f"NOTE: only {len(chosen)} quotable xStocks available, fewer than 10.")

    save(OUT, {
        "fixedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "chain": okx_dex.X_LAYER,
        "probeNotionalUsd": PROBE_USD,
        "selectionBasis": "lowest observed price impact on a live $5 USDC quote; NVDAx pinned",
        "usdc": {"symbol": usdc.get("tokenSymbol"),
                 "address": usdc.get("tokenContractAddress"),
                 "decimals": decimals_of(usdc, 6)},
        "xstocksOnChain": universe_count,
        "probed": len(cache),
        "quotable": len(quotable),
        "constituents": [{
            "symbol": e["symbol"], "name": e.get("name"), "address": e["address"],
            "decimals": e["decimals"], "priceImpactPctAtProbe": e.get("priceImpactPct"),
            "multiplierAtFix": e.get("multiplier"),
        } for e in chosen],
    })

    print(f"\nfixed {len(chosen)} constituents -> {OUT}")
    for e in chosen:
        print(f"  {e['symbol']:<10} impact={e.get('priceImpactPct')} {e['address']}")


def main():
    usdc, stocks = phase_universe()
    if usdc is None:
        return 1

    cache, remaining = phase_probe(usdc, stocks)

    if not any(e.get("quotable") for e in cache.values()):
        print("No quotable xStock yet — not fixing a set.", file=sys.stderr)
        return 1

    phase_select(usdc, cache, len(stocks))
    if remaining:
        print(f"\n{remaining} tokens still unprobed. Re-run to continue; the set "
              f"will be refined as more liquidity data arrives.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
