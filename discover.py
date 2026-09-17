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
DEPTH_SMALL_USD = 1.0
DEPTH_LARGE_USD = 50.0
TARGET_SET = int(os.environ.get("VECTRA_SET_SIZE", "14"))
MAX_PROBE = int(os.environ.get("VECTRA_MAX_PROBE", "0"))  # 0 = no limit
# 1.1s produced a success pattern inconsistent with real liquidity (TSLAx dead
# while DELLx quoted), which points at throttling rather than market depth.
THROTTLE_S = float(os.environ.get("VECTRA_THROTTLE", "3.0"))
FLUSH_EVERY = 10
# Bump when a probe result becomes untrustworthy; forces a full re-probe.
PROBE_VERSION = 2

# Codes and signals that mean "we were refused", not "this token has no route".
RATE_LIMIT_CODES = {"50011", "50013", "50061", "429"}
RATE_LIMIT_HINTS = ("too many requests", "rate limit", "requests too frequent",
                    "system busy", "try again")
# Faults on our side of the call, never facts about the token.
# 50050 is the v5 deprecation notice that produced 594 false "no route" results.
CLIENT_ERROR_CODES = {"50050", "50000", "50001", "50100", "50110", "50111",
                      "50112", "50113", "50114"}

UNIVERSE = Path("data/xstocks_all.json")
PROBE = Path("data/liquidity_probe.json")
OUT = Path("data/constituents.json")
RANKING = Path("data/ranking.md")


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

    def needs_probe(t):
        key = (t.get("tokenContractAddress") or "").lower()
        if key not in cache:
            return True
        e = cache[key]
        # Results from an earlier probe version were produced against the
        # deprecated v5 endpoint with the v6 error masked. They are not
        # evidence and are discarded rather than trusted.
        if e.get("probeVersion") != PROBE_VERSION:
            return True
        # Unknowns are refusals, not results. Always retry them.
        return e.get("outcome") == "unknown"

    todo = [t for t in stocks if needs_probe(t)]
    if MAX_PROBE:
        todo = todo[:MAX_PROBE]

    retries = sum(1 for t in todo
                  if (t.get("tokenContractAddress") or "").lower() in cache)
    print(f"probe: {len(cache)} cached, {len(todo)} to go "
          f"({retries} of them retries of earlier refusals), "
          f"~{len(todo) * THROTTLE_S / 60:.1f} min at {THROTTLE_S}s spacing")

    dec_in = decimals_of(usdc, 6)
    amount = int(round(PROBE_USD * 10 ** dec_in))
    done = 0

    try:
        for t in todo:
            addr = t["tokenContractAddress"]
            key = addr.lower()
            entry = {"symbol": t.get("tokenSymbol"), "name": t.get("tokenName"),
                     "address": addr, "decimals": decimals_of(t),
                     "probeVersion": PROBE_VERSION,
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
                              "routes": okx_dex.routes_of(d),
                              "rawKeys": sorted(d.keys())})
                entry["outcome"] = "quotable" if out_units > 0 else "no_route"
            else:
                msg = str(body.get("msg") if isinstance(body, dict) else body)[:160]
                code = str(body.get("code") if isinstance(body, dict) else "?")
                refused = (
                    status in (429, 0)
                    or code in RATE_LIMIT_CODES
                    or code in CLIENT_ERROR_CODES
                    or any(h in msg.lower() for h in RATE_LIMIT_HINTS)
                    or (isinstance(body, dict) and "transport_error" in body)
                )
                entry["attempts"] = body.get("attempts") if isinstance(body, dict) else None
                # A refusal is not a fact about the token. It is recorded as
                # unknown, kept out of the liquidity columns entirely, and
                # retried on the next run.
                entry.update({
                    "quotable": False,
                    "priceImpactPct": None,
                    "outcome": "unknown" if refused else "no_route",
                    "error": f"http={status} code={code} msg={msg}"[:200],
                })

            mult, mult_raw = xlayer.multiplier(addr)
            entry["multiplier"] = mult
            entry["multiplierRaw"] = str(mult_raw) if mult_raw is not None else None

            cache[key] = entry
            done += 1
            flag = {"quotable": "ok     ", "no_route": "NO-ROUTE",
                    "unknown": "REFUSED"}[entry["outcome"]]
            detail = "" if entry["outcome"] == "quotable" else f" {entry.get('error','')[:60]}"
            print(f"  [{done}/{len(todo)}] {entry['symbol']:<10} {flag} "
                  f"mult={mult}{detail}")

            if done % FLUSH_EVERY == 0:
                save(PROBE, cache)
            time.sleep(THROTTLE_S)
    except KeyboardInterrupt:
        print("interrupted — flushing cache", file=sys.stderr)
    finally:
        save(PROBE, cache)

    counts = {"quotable": 0, "no_route": 0, "unknown": 0}
    for e in cache.values():
        counts[e.get("outcome", "unknown")] = counts.get(e.get("outcome", "unknown"), 0) + 1
    remaining = len([t for t in stocks if needs_probe(t)])

    print(f"\nprobe cache: {len(cache)} entries — "
          f"{counts['quotable']} quotable, {counts['no_route']} no route, "
          f"{counts['unknown']} refused (unknown)")
    if counts["unknown"]:
        print(f"  {counts['unknown']} refusals are NOT liquidity findings. "
              f"Re-run to retry them; raise VECTRA_THROTTLE if they persist.")
    print(f"  {remaining} still to probe")
    return cache, remaining


def phase_depth(usdc, cache):
    """Measure real slippage on the quotable set.

    The aggregator returns priceImpactPercentage as null on this chain, so
    ranking by it is meaningless. Depth is measured instead: quote the same
    token small and large, and read how far the rate degrades. That is the
    quantity the spec actually cares about, observed rather than self-reported.
    """
    quotable = [e for e in cache.values() if e.get("quotable")]
    if not quotable:
        return

    dec_in = decimals_of(usdc, 6)
    small = int(round(DEPTH_SMALL_USD * 10 ** dec_in))
    large = int(round(DEPTH_LARGE_USD * 10 ** dec_in))
    todo = [e for e in quotable if "depthPct" not in e]
    print(f"\ndepth: measuring {len(todo)} quotable tokens at "
          f"${DEPTH_SMALL_USD:g} vs ${DEPTH_LARGE_USD:g}")

    def rate(addr, amount, dec_out):
        status, body = okx_dex.quote(usdc["tokenContractAddress"], addr, amount)
        if not (isinstance(body, dict) and body.get("code") in ("0", 0) and body.get("data")):
            return None
        d = body["data"][0] if isinstance(body["data"], list) else body["data"]
        try:
            out = int(d.get("toTokenAmount") or 0)
        except (TypeError, ValueError):
            return None
        if out <= 0:
            return None
        return (out / 10 ** dec_out) / (amount / 10 ** dec_in)

    for i, e in enumerate(todo, 1):
        addr, dec_out = e["address"], e["decimals"]
        r_small = rate(addr, small, dec_out)
        time.sleep(THROTTLE_S)
        r_large = rate(addr, large, dec_out)
        time.sleep(THROTTLE_S)
        if r_small and r_large:
            # Positive means you get proportionally less per dollar when larger.
            e["depthPct"] = (r_small - r_large) / r_small * 100
            e["rateSmall"], e["rateLarge"] = r_small, r_large
        else:
            e["depthPct"] = None
            e["depthError"] = "one or both sizes returned no route"
        print(f"  [{i}/{len(todo)}] {e['symbol']:<10} depth={e['depthPct']}")
        save(PROBE, cache)


def phase_select(usdc, cache, universe_count):
    quotable = [e for e in cache.values() if e.get("quotable")]
    # Rank by measured depth where available, falling back to reported impact.
    quotable.sort(key=lambda e: (
        e.get("depthPct") is None and e.get("priceImpactPct") is None,
        e.get("depthPct") if e.get("depthPct") is not None
        else (e.get("priceImpactPct") or 0),
    ))

    counts = {"quotable": 0, "no_route": 0, "unknown": 0}
    for e in cache.values():
        k = e.get("outcome", "unknown")
        counts[k] = counts.get(k, 0) + 1

    lines = ["# Quotable xStocks on X Layer, ranked by measured depth", "",
             f"Universe: {universe_count} xStocks. Probed: {len(cache)}.", "",
             f"- **{counts['quotable']}** quotable at ${PROBE_USD:g}",
             f"- **{counts['no_route']}** returned no route (a liquidity finding)",
             f"- **{counts['unknown']}** were refused by the API "
             f"(rate limit or transport — **not** a liquidity finding, retried on re-run)",
             "",
             f"Depth is the percentage the rate degrades between a "
             f"${DEPTH_SMALL_USD:g} and a ${DEPTH_LARGE_USD:g} quote. "
             f"Lower is deeper.", "",
             "| # | Symbol | Depth % | Multiplier | Address |",
             "|---|--------|---------|------------|---------|"]
    for i, e in enumerate(quotable, 1):
        d = e.get("depthPct")
        lines.append(f"| {i} | {e['symbol']} | "
                     f"{'—' if d is None else f'{d:.4f}'} | "
                     f"{e.get('multiplier')} | `{e['address']}` |")
    lines += ["", "This is the menu. The recording set below is a provisional "
                  "default taken from the top of it; choose the index deliberately."]
    RANKING.parent.mkdir(parents=True, exist_ok=True)
    RANKING.write_text("\n".join(lines) + "\n")
    print(f"\nfull ranking -> {RANKING}")

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

    phase_depth(usdc, cache)
    save(PROBE, cache)
    phase_select(usdc, cache, len(stocks))
    if remaining:
        print(f"\n{remaining} tokens still unprobed. Re-run to continue; the set "
              f"will be refined as more liquidity data arrives.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
