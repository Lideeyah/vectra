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
# Overridable so a specific question can be asked without editing code —
# e.g. VECTRA_LADDER="1,2" to find out whether a $1 leg routes at all.
# `or` not a default argument: a blank workflow input arrives as an empty
# STRING, not as an unset variable, and "".split(",") is [""], which is a
# ValueError rather than the default ladder.
LADDER = [float(x) for x in
          (os.environ.get("VECTRA_LADDER") or "1,5,10,25,50,100").split(",")
          if x.strip()]
THROTTLE_S = 3.0
THIN_TAIL_COUNT = 3   # worst-measured quotable assets, graded alongside the set
# A non-default ladder writes to its OWN file. The default-ladder result is
# the evidence SPEC 2A cites for the 0.0008%-to-5.74% range, and a narrower
# run would otherwise silently overwrite it with two data points. Derived from
# the ladder rather than passed in, so there is nothing to remember.
_DEFAULT_LADDER = [1.0, 5.0, 10.0, 25.0, 50.0, 100.0]
OUT = Path("data/verifications/depth_curve.json") if LADDER == _DEFAULT_LADDER \
    else Path("data/verifications/depth_curve_"
              + "-".join(f"{u:g}" for u in LADDER) + ".json")

CONSTITUENTS = Path("data/constituents.json")


def default_tokens():
    """The whole recording set by default.

    The original depth column came from two quotes taken seconds apart, so every
    figure in it carries whatever the underlying did between the two calls. The
    ladder replaces it: one pass per asset, no gap for price to move through.
    """
    if not CONSTITUENTS.exists():
        return {"MSTRx": "0xae2f842ef90c0d5213259ab82639d5bbf649b08e",
                "SPYx": "0x90a2a4c76b5d8c0bc892a69ea28aa775a8f2dd48"}

    c = json.loads(CONSTITUENTS.read_text())
    tokens = {x["symbol"]: x["address"] for x in c["constituents"]}

    # The thin tail is not in the recording set, but it carried the widest
    # figures in the old depth column and supplies the spread that made the
    # proportionality story persuasive. A run over the constituents alone would
    # leave those numbers unmeasured rather than confirmed or killed, so the
    # worst-measured quotable assets are graded alongside.
    #
    # Note what this selection can and cannot show. These ranks come from the
    # flawed two-quote method, so "the three worst" is itself an artifact of it;
    # the genuinely thinnest assets may be elsewhere entirely. Grading these
    # three tests the numbers the claim was built on, which is the point. But if
    # they collapse, the conclusion is NOT that the tail was found and then
    # disproved — it is that the old method could not identify a tail at all.
    # Establishing whether a real tail exists would need a ladder across the
    # whole quotable set, which is a separate run.
    probe = Path("data/liquidity_probe.json")
    if probe.exists():
        entries = [e for e in json.loads(probe.read_text()).values()
                   if e.get("quotable") and e.get("depthPct") is not None]
        entries.sort(key=lambda e: -e["depthPct"])
        for e in entries[:THIN_TAIL_COUNT]:
            tokens.setdefault(e["symbol"], e["address"])
    return tokens


def original_depths():
    """The superseded two-quote figures, for the survives-or-drift comparison."""
    probe = Path("data/liquidity_probe.json")
    if not probe.exists():
        return {}
    return {e["symbol"]: e.get("depthPct")
            for e in json.loads(probe.read_text()).values()
            if e.get("depthPct") is not None}


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
        # An "improvement" must exceed measurement noise. Rates differing in the
        # eighth decimal are identical for this purpose, and treating them as an
        # improvement produced a false ROUTING ARTIFACT verdict on SPYx.
        IMPROVE_THRESHOLD_PCT = 0.001
        gain = (best["rate"] - ok[0]["rate"]) / ok[0]["rate"] * 100
        improves = best["usd"] > ok[0]["usd"] and gain > IMPROVE_THRESHOLD_PCT

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
            worst_delta = (ok[-1]["rate"] - ok[0]["rate"]) / ok[0]["rate"] * 100
            verdict = (f"NORMAL: the rate does not meaningfully improve with "
                       f"size (best is {gain:+.4f}% vs the smallest, within "
                       f"noise). Cost degrades monotonically as expected: "
                       f"{worst_delta:+.4f}% from ${ok[0]['usd']:g} to "
                       f"${ok[-1]['usd']:g}.")
        print(f"\n  VERDICT: {verdict}")
    return {"symbol": symbol, "address": addr, "rows": rows, "verdict": verdict}


def main():
    tokens = default_tokens()
    env = os.environ.get("VECTRA_TOKENS")
    if env:
        tokens = dict(pair.split("=", 1) for pair in env.split(",") if "=" in pair)

    print("Depth curve — read-only, quotes only, nothing is sent.")
    print(f"ladder: {', '.join(f'${u:g}' for u in LADDER)}")

    results = [run(sym, addr) for sym, addr in tokens.items()]

    # Which of the original depth figures survive, and which were drift.
    old = original_depths()
    print("\n" + "=" * 74)
    print("ORIGINAL TWO-QUOTE DEPTH vs SINGLE-PASS LADDER")
    print("=" * 74)
    print(f"{'SYMBOL':<9} {'OLD $1->$50':>13} {'LADDER $1->$50':>16} "
          f"{'$1->$100':>11}  VERDICT")
    summary = []
    for r in results:
        ok = {x["usd"]: x for x in r["rows"] if x.get("ok")}
        if 1.0 not in ok:
            continue
        base = ok[1.0]["rate"]
        d50 = -((ok[50.0]["rate"] - base) / base * 100) if 50.0 in ok else None
        d100 = -((ok[100.0]["rate"] - base) / base * 100) if 100.0 in ok else None
        o = old.get(r["symbol"])
        if o is None or d50 is None:
            verdict = "no comparison"
        # Combined tolerance. A fixed 0.005pp bar is punishing on a 2% figure
        # and lax on a 0.002% one, and the table spans three orders of
        # magnitude, so absolute agreement OR relative agreement counts.
        elif abs(o - d50) <= 0.005 or abs(o - d50) / max(abs(o), 1e-9) <= 0.25:
            verdict = "agrees"
        else:
            verdict = f"DIVERGES (off by {o - d50:+.4f}pp)"
        summary.append({"symbol": r["symbol"], "originalDepthPct": o,
                        "ladder50Pct": d50, "ladder100Pct": d100,
                        "verdict": verdict})
        print(f"{r['symbol']:<9} {('—' if o is None else f'{o:.4f}%'):>13} "
              f"{('—' if d50 is None else f'{d50:.4f}%'):>16} "
              f"{('—' if d100 is None else f'{d100:.4f}%'):>11}  {verdict}")

    survived = sum(1 for s_ in summary if s_["verdict"] == "agrees")
    print(f"\n{survived} of {len(summary)} original figures agree with the "
          f"ladder; {len(summary) - survived} diverge.")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "ladderUsd": LADDER, "results": results, "comparison": summary,
    }, indent=2) + "\n")
    print(f"\nwritten to {OUT}")
    return 0 if any(r["verdict"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
