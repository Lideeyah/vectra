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
                          "targetWeightBps": t["weightBps"]})

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


def select_leg(m, state):
    """The single leg that most reduces total distance from target.

    Only USDC-funded buys are selected in this version: selling is permitted by
    the contract but the initial build is buy-only, matching SPEC 9.1.
    """
    tradeable = [p for p in state["positions"]
                 if p["priceUsd"] and p["driftBps"] < 0]
    if not tradeable:
        return None, "no position is below target with a usable price"

    # Most underweight first — that is the leg that reduces distance most.
    worst = min(tradeable, key=lambda p: p["driftBps"])
    if abs(worst["driftBps"]) <= m["driftToleranceBps"]:
        return None, (f"largest drift {abs(worst['driftBps'])}bps is within "
                      f"tolerance {m['driftToleranceBps']}bps")

    # Size: close the gap, capped by the leg limit, the cap, and cash on hand.
    gap_usd = (abs(worst["driftBps"]) / 10_000) * state["totalUsd"]
    remaining_cap = m["totalCapUsdc"] - m["spentUsdc"]
    size = min(gap_usd, m["maxLegUsdc"], remaining_cap, state["usdcValueUsd"])

    if remaining_cap <= 0:
        return None, "total spend cap reached"
    if state["usdcValueUsd"] <= 0:
        return None, "owner holds no USDC"
    if size < 0.01:
        return None, f"computed leg size ${size:.4f} below the minimum"

    return {"tokenIn": "USDC", "tokenInAddress": USDC,
            "tokenOut": worst["symbol"], "tokenOutAddress": worst["address"],
            "amountUsd": round(size, 6),
            "driftBps": worst["driftBps"],
            "reason": f"{worst['symbol']} is {abs(worst['driftBps'])}bps below target"}, None


def build_payload(leg):
    """The swap payload the contract would forward.

    userWalletAddress is the CONTRACT, not the owner: the calldata encodes its
    caller, and a payload built for the owner will not work when the contract is
    the one calling. v6 names the slippage parameter slippagePercent.
    """
    if not CONTRACT:
        return None, "no contract deployed; payload not requested"

    amount = int(round(leg["amountUsd"] * 10 ** USDC_DECIMALS))
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
        print(f"\nLEG: buy {leg['tokenOut']} with ${leg['amountUsd']} USDC "
              f"({leg['reason']})")
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
    out.write_text(json.dumps({
        "ts": started.isoformat(timespec="seconds"),
        "mode": "execute" if EXECUTE else "dry-run",
        "owner": m["owner"], "contract": CONTRACT or None,
        "totalUsd": state["totalUsd"], "usdcValueUsd": state["usdcValueUsd"],
        "positions": state["positions"],
        "leg": leg, "noActionReason": why_not,
        "payload": payload, "payloadError": payload_err,
        "refusals": state["refusals"],
    }, indent=2) + "\n")
    print(f"\nlogged {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
