"""Vectra agent. One convergence cycle.

Reads the mandate and the owner's actual position, prices it with live
aggregator quotes, computes the distance from target in weight space, and
selects the single leg that most reduces that distance.

DRY RUN BY DEFAULT. It builds and logs the transaction it would send and stops
there. Sending requires VECTRA_EXECUTE=1 and a keeper key, and the contract is
not deployed yet, so nothing can be sent today.

The division of labour, per SPEC 5.2: the contract bounds direction and size;
this does the weight-space optimisation the contract cannot. Every refusal is
recorded with its reason — the log of what the agent declined to do is as much a
product surface as the log of what it did.
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import okx_dex
import xlayer

CHAIN = "196"
USDC = "0xb6ceceab302e2e4948951ee7843fc24e92933061"
USDC_DECIMALS = 6

# Verified live (data/verifications/swap.json).
ROUTER = "0x7c5bEE2a8091C3ef39072f64F18Fac913060AEaF"
SPENDER = "0x8b773D83bc66Be128c60e07E17C8901f7a64F000"

CONTRACT = os.environ.get("VECTRA_CONTRACT", "")
MANDATE_FILE = Path("data/agent/mandate.json")
LOG_DIR = Path("data/agent")

PRICE_NOTIONAL_USD = 5.0     # size at which positions are valued
SLIPPAGE_PERCENT = "0.5"
THROTTLE_S = 1.1
SANITY_BAND = 0.25           # reject a price 25% off the previous cycle

# The contract refuses a leg that moves more than maxLegBpsOfTarget of a
# token's target share count — in EITHER direction. A favourable fill legitimately
# delivers more than quoted, so a leg sized AT the bound is reverted by ordinary
# positive slippage, and the refusal log then shows a rate-limit breach on a
# trade that was simply better than expected. That works in testing and refuses
# every leg on a volatile day. Size beneath the ceiling, never against it.
RATE_HEADROOM = 0.80
EXECUTE = os.environ.get("VECTRA_EXECUTE") == "1"

SEL_BALANCE_OF = "0x70a08231"
SEL_ALLOWANCE = "0xdd62ed3e"


def now():
    return datetime.now(timezone.utc)


def pad_addr(a):
    return a.lower().replace("0x", "").rjust(64, "0")


def read_uint(to, data):
    try:
        r = xlayer.eth_call(to, data)
    except Exception:
        return None
    if "error" in r:
        return None
    v = r.get("result") or "0x"
    return int(v, 16) if len(v) == 66 else None


def balance_of(token, holder):
    return read_uint(token, SEL_BALANCE_OF + pad_addr(holder))


def allowance(token, owner, spender):
    return read_uint(token, SEL_ALLOWANCE + pad_addr(owner) + pad_addr(spender))


def load_mandate():
    """From chain when the contract is deployed; from file until then.

    The file form exists so the decision engine is exercisable before
    deployment. It is never a substitute for the on-chain mandate: when
    VECTRA_CONTRACT is set, chain state is the only source.
    """
    if CONTRACT:
        raise SystemExit(
            "On-chain mandate reads are not wired yet — the contract is not "
            "deployed. Unset VECTRA_CONTRACT to run against data/agent/mandate.json."
        )
    if not MANDATE_FILE.exists():
        raise SystemExit(f"No mandate at {MANDATE_FILE}")
    return json.loads(MANDATE_FILE.read_text())


def previous_prices():
    """Last cycle's unit prices, for the sanity band."""
    logs = sorted(LOG_DIR.glob("cycle_*.json"))
    if not logs:
        return {}
    try:
        prev = json.loads(logs[-1].read_text())
    except json.JSONDecodeError:
        return {}
    return {p["symbol"]: p["priceUsd"] for p in prev.get("positions", [])
            if p.get("priceUsd")}


def price_token(addr, decimals):
    """USD per whole token, from a live quote at the valuation notional."""
    amount = int(round(PRICE_NOTIONAL_USD * 10 ** USDC_DECIMALS))
    status, body = okx_dex.quote(USDC, addr, amount)
    if not (isinstance(body, dict) and body.get("code") in ("0", 0) and body.get("data")):
        atts = (body.get("attempts") if isinstance(body, dict) else None) or []
        if atts:
            detail = "; ".join(f"{a['path'].rsplit('/', 2)[0][-3:]} code={a['code']} "
                               f"{a['msg'][:60]}" for a in atts)
        else:
            detail = str(body)[:160]
        return None, f"quote failed: {detail}"
    d = body["data"][0] if isinstance(body["data"], list) else body["data"]
    try:
        out = int(d.get("toTokenAmount") or 0)
    except (TypeError, ValueError):
        return None, "unparseable toTokenAmount"
    if out <= 0:
        return None, "no route at valuation size"
    tokens_out = out / 10 ** decimals
    return PRICE_NOTIONAL_USD / tokens_out, None


def build_state(m):
    """Read the position fresh and value it. Nothing is cached across a cycle."""
    owner = m["owner"]
    prev = previous_prices()
    positions, refusals = [], []

    for t in m["basket"]:
        addr, sym, dec = t["address"], t["symbol"], int(t["decimals"])

        # Read balance and shares fresh, at the point of use.
        bal = balance_of(addr, owner)
        mult, _ = xlayer.multiplier(addr)
        sh = read_uint(addr, "0xf5eb42dc" + pad_addr(owner))  # sharesOf

        price, err = price_token(addr, dec)
        time.sleep(THROTTLE_S)

        if price is None:
            refusals.append({"token": sym, "reason": err})
            positions.append({"symbol": sym, "address": addr, "decimals": dec,
                              "balance": bal, "shares": sh, "multiplier": mult,
                              "priceUsd": None, "valueUsd": None,
                              "targetWeightBps": t["weightBps"]})
            continue

        # Sanity band against the previous cycle.
        if sym in prev and prev[sym]:
            drift = abs(price - prev[sym]) / prev[sym]
            if drift > SANITY_BAND:
                refusals.append({
                    "token": sym,
                    "reason": f"price moved {drift*100:.1f}% since last cycle "
                              f"({prev[sym]:.4f} -> {price:.4f}); outside sanity band"})
                price = None

        value = (bal / 10 ** dec) * price if (bal is not None and price) else None
        positions.append({"symbol": sym, "address": addr, "decimals": dec,
                          "balance": bal, "shares": sh, "multiplier": mult,
                          "priceUsd": price, "valueUsd": value,
                          "targetWeightBps": t["weightBps"],
                          "targetShares": t.get("targetShares")})

    usdc_bal = balance_of(USDC, owner)
    usdc_value = (usdc_bal or 0) / 10 ** USDC_DECIMALS
    invested = sum(p["valueUsd"] or 0 for p in positions)
    total = invested + usdc_value

    for p in positions:
        p["actualWeightBps"] = (
            int(round((p["valueUsd"] or 0) / total * 10_000)) if total > 0 else 0)
        p["driftBps"] = p["actualWeightBps"] - p["targetWeightBps"]

    return {"positions": positions, "usdcBalance": usdc_bal,
            "usdcValueUsd": usdc_value, "investedUsd": invested,
            "totalUsd": total, "refusals": refusals}


def distance_bps(values, total, targets):
    """Total distance from target, as the sum of absolute weight errors.

    L1 rather than squared error: the contract permits one leg per cycle, and L1
    makes the single best leg the one closing the largest single gap, which is
    what convergence one step at a time actually wants.
    """
    if total <= 0:
        return sum(abs(t) for t in targets)
    return sum(abs((v / total) * 10_000 - t) for v, t in zip(values, targets))


def rate_cap_usd(m, p):
    """The contract's share-denominated rate bound, converted to dollars.

    targetShares * bps / 10000 gives the share movement the contract permits.
    Shares are converted to balance by the multiplier and to dollars by the
    quoted price, then held under the ceiling by RATE_HEADROOM so that a
    favourable fill does not push the leg over it.
    """
    target_shares = p.get("targetShares")
    bps = m.get("maxLegBpsOfTarget")
    if not target_shares or not bps or not p.get("priceUsd"):
        return float("inf")
    allowed_shares = target_shares * bps / 10_000
    mult = p.get("multiplier") or 1.0
    allowed_tokens = allowed_shares * mult / 10 ** p["decimals"]
    return allowed_tokens * p["priceUsd"] * RATE_HEADROOM


def evaluate_legs(m, state):
    """Every admissible leg in both directions, with the distance each reaches.

    A leg is admissible if it moves a position toward target. Sizing is bounded
    by the drift gap, the per-leg limit, and what is actually available to
    spend or sell.
    """
    tol = m["driftToleranceBps"]
    positions = state["positions"]
    total = state["totalUsd"]
    remaining_cap = m["totalCapUsdc"] - m["spentUsdc"]

    values = [p["valueUsd"] or 0 for p in positions]
    targets = [p["targetWeightBps"] for p in positions]
    before = distance_bps(values, total, targets)

    candidates = []
    for i, p in enumerate(positions):
        if not p["priceUsd"] or abs(p["driftBps"]) <= tol:
            continue
        gap_usd = (abs(p["driftBps"]) / 10_000) * total

        # The contract's rate bound, expressed in dollars so it can be compared
        # with the other limits, and held under rather than met exactly.
        rate_usd = rate_cap_usd(m, p)

        if p["driftBps"] < 0:
            # Underweight: buy with USDC. Spending consumes cap headroom.
            size = min(gap_usd, m["maxLegUsdc"], remaining_cap,
                       state["usdcValueUsd"], rate_usd)
            direction, delta = "buy", +1
        else:
            # Overweight: sell into USDC. A sell commits no new capital, so it
            # does not consume cap headroom — see SPEC 5.2 on the cap decision.
            size = min(gap_usd, m["maxLegUsdc"], p["valueUsd"] or 0, rate_usd)
            direction, delta = "sell", -1

        if size < 0.01:
            continue

        trial = list(values)
        trial[i] += delta * size
        after = distance_bps(trial, total, targets)
        candidates.append({
            "direction": direction, "symbol": p["symbol"],
            "address": p["address"], "amountUsd": round(size, 6),
            "priceUsd": p["priceUsd"], "decimals": p["decimals"],
            "driftBps": p["driftBps"],
            "distanceBefore": round(before, 2),
            "distanceAfter": round(after, 2),
            "reductionBps": round(before - after, 2),
        })

    candidates.sort(key=lambda c: -c["reductionBps"])
    return before, candidates


def select_leg(m, state):
    """The single leg that most reduces total distance from target.

    Both directions are considered. A buy-only agent cannot converge from an
    overweight position, which is most of the product's job — the contract was
    built symmetric and the agent now matches it.
    """
    tol = m["driftToleranceBps"]
    priced = [p for p in state["positions"] if p["priceUsd"]]
    if not priced:
        return None, "no position has a usable price this cycle"

    largest = max(priced, key=lambda p: abs(p["driftBps"]))
    if abs(largest["driftBps"]) <= tol:
        return None, (f"largest drift {abs(largest['driftBps'])}bps is within "
                      f"tolerance {tol}bps")

    before, candidates = evaluate_legs(m, state)
    state["distanceBefore"] = round(before, 2)
    state["candidates"] = candidates

    if candidates:
        best = candidates[0]
        leg = {
            "direction": best["direction"],
            "symbol": best["symbol"],
            "tokenIn": "USDC" if best["direction"] == "buy" else best["symbol"],
            "tokenInAddress": USDC if best["direction"] == "buy" else best["address"],
            "tokenOut": best["symbol"] if best["direction"] == "buy" else "USDC",
            "tokenOutAddress": best["address"] if best["direction"] == "buy" else USDC,
            "amountUsd": best["amountUsd"],
            "priceUsd": best["priceUsd"],
            "decimals": best["decimals"],
            "driftBps": best["driftBps"],
            "distanceBefore": best["distanceBefore"],
            "distanceAfter": best["distanceAfter"],
            "reductionBps": best["reductionBps"],
            "rejected": candidates[1:],
            "reason": (f"{best['symbol']} is {abs(best['driftBps'])}bps "
                       f"{'below' if best['driftBps'] < 0 else 'above'} target; "
                       f"this leg cuts total distance from "
                       f"{best['distanceBefore']} to {best['distanceAfter']}bps"),
        }
        return leg, None

    # Nothing admissible. Name the binding constraint, not the first blocker.
    under = [p for p in priced if p["driftBps"] < -tol]
    over = [p for p in priced if p["driftBps"] > tol]
    remaining_cap = m["totalCapUsdc"] - m["spentUsdc"]

    if remaining_cap <= 0 and under and not over:
        return None, (f"total spend cap reached "
                      f"(${m['spentUsdc']:.2f} of ${m['totalCapUsdc']:.2f}); "
                      f"buying is blocked and nothing is above target to sell")

    blockers = []
    for p in under:
        need = min((abs(p["driftBps"]) / 10_000) * state["totalUsd"], m["maxLegUsdc"])
        if state["usdcValueUsd"] < 0.01:
            blockers.append(f"{p['symbol']} needs ~${need:.2f} but the owner "
                            f"holds no USDC")
        elif remaining_cap < 0.01:
            blockers.append(f"{p['symbol']} needs ~${need:.2f} but the spend "
                            f"cap has ${remaining_cap:.2f} left")
        else:
            blockers.append(f"{p['symbol']} leg sizes below the ${0.01:.2f} minimum")
    for p in over:
        blockers.append(f"{p['symbol']} is +{p['driftBps']}bps but its sellable "
                        f"value is ${p['valueUsd'] or 0:.2f}")

    return None, ("no admissible leg: " + "; ".join(blockers)) if blockers else (
        None, "no admissible leg this cycle")


def build_payload(leg):
    """The swap payload the contract would forward.

    userWalletAddress is the CONTRACT, not the owner: the calldata encodes its
    caller, and a payload built for the owner will not work when the contract is
    the one calling. v6 names the slippage parameter slippagePercent.
    """
    if not CONTRACT:
        return None, "no contract deployed; payload not requested"

    # A sell sends the rebasing token, so the amount is in that token's units,
    # not USDC's. Getting this wrong would send a swap sized by a factor of 1e12.
    if leg["direction"] == "buy":
        amount = int(round(leg["amountUsd"] * 10 ** USDC_DECIMALS))
    else:
        tokens = leg["amountUsd"] / leg["priceUsd"]
        amount = int(round(tokens * 10 ** leg["decimals"]))
    status, body, _ = okx_dex.endpoint("swap", {
        "amount": str(amount),
        "fromTokenAddress": leg["tokenInAddress"],
        "toTokenAddress": leg["tokenOutAddress"],
        "slippagePercent": SLIPPAGE_PERCENT,
        "userWalletAddress": CONTRACT,
    }, CHAIN)
    if not (isinstance(body, dict) and body.get("code") in ("0", 0) and body.get("data")):
        return None, f"swap payload refused: {json.dumps(body)[:200]}"

    d = body["data"][0] if isinstance(body["data"], list) else body["data"]
    tx = d.get("tx") or {}
    if (tx.get("to") or "").lower() != ROUTER.lower():
        return None, (f"router mismatch: payload targets {tx.get('to')}, "
                      f"expected {ROUTER}")

    return {"to": tx.get("to"), "data": tx.get("data"),
            "gas": tx.get("gas"), "minReceiveAmount": tx.get("minReceiveAmount"),
            "routes": okx_dex.routes_of(d)}, None


def main():
    m = load_mandate()
    started = now()
    print(f"cycle {started:%Y-%m-%d %H:%M:%S}Z   owner {m['owner']}")
    print(f"mode: {'EXECUTE' if EXECUTE else 'DRY RUN — nothing will be sent'}\n")

    state = build_state(m)

    print(f"{'SYMBOL':<9} {'PRICE':>11} {'VALUE':>10} {'ACTUAL':>8} {'TARGET':>8} {'DRIFT':>8}")
    for p in state["positions"]:
        price = f"{p['priceUsd']:.4f}" if p["priceUsd"] else "—"
        val = f"{p['valueUsd']:.2f}" if p["valueUsd"] else "—"
        print(f"{p['symbol']:<9} {price:>11} {val:>10} "
              f"{p['actualWeightBps']:>7}b {p['targetWeightBps']:>7}b "
              f"{p['driftBps']:>+7}b")
    print(f"\nUSDC {state['usdcValueUsd']:.2f}   invested {state['investedUsd']:.2f}"
          f"   total {state['totalUsd']:.2f}")

    # Documented gap: the issuer asks integrations to pause around multiplier
    # activation, and those timestamps are not obtainable (SPEC 16). Recorded
    # every cycle so the omission is visible rather than silent.
    state["refusals"].append({
        "token": "*",
        "reason": "multiplier activation windows unavailable — cannot honour "
                  "the issuer's pause requirement (SPEC 14, open item)"})

    leg, why_not = select_leg(m, state)
    payload, payload_err = (None, None)
    if leg:
        print(f"\nLEG: {leg['direction'].upper()} {leg['symbol']} "
              f"${leg['amountUsd']:.2f}")
        print(f"  {leg['reason']}")
        for r in leg["rejected"]:
            print(f"  rejected: {r['direction']} {r['symbol']} ${r['amountUsd']:.2f} "
                  f"-> {r['distanceAfter']}bps (cuts {r['reductionBps']}bps)")
        payload, payload_err = build_payload(leg)
        if payload:
            print(f"  router {payload['to']}  gas {payload['gas']}")
            print(f"  routes {' | '.join(payload['routes'])}")
        else:
            print(f"  no payload: {payload_err}")
    else:
        print(f"\nNO ACTION: {why_not}")

    for r in state["refusals"]:
        print(f"  refused [{r['token']}]: {r['reason']}")

    if EXECUTE:
        print("\nEXECUTE requested but sending is not implemented: the contract "
              "is not deployed. Nothing sent.", file=sys.stderr)

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    out = LOG_DIR / f"cycle_{started:%Y%m%dT%H%M%S}Z.json"
    payload_json = json.dumps({
        "ts": started.isoformat(timespec="seconds"),
        "mode": "execute" if EXECUTE else "dry-run",
        "owner": m["owner"], "contract": CONTRACT or None,
        "totalUsd": state["totalUsd"], "usdcValueUsd": state["usdcValueUsd"],
        "positions": state["positions"],
        "leg": leg, "noActionReason": why_not,
        "payload": payload, "payloadError": payload_err,
        "refusals": state["refusals"],
    }, indent=2) + "\n"

    out.write_text(payload_json)

    # Also written to a STABLE path. The timestamped file is the archive; this
    # is what a browser can actually fetch, because raw file hosting serves
    # files and not directory listings, so a timestamped name is unreachable
    # without an index. The interface's next-move panel and refusal log both
    # depend on this, and its `ts` field is what lets the interface tell a
    # stopped agent from a stable position.
    (LOG_DIR / "latest.json").write_text(payload_json)

    print(f"\nlogged {out} and data/agent/latest.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
