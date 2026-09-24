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
# Overridable so a cycle can be run against a scratch directory without
# writing into the committed record, which is append-only and real.
LOG_DIR = Path(os.environ.get("VECTRA_LOG_DIR", "data/agent"))

PRICE_NOTIONAL_USD = 5.0     # size at which positions are valued
# Slippage requested from the aggregator, which sets the router's OWN minimum
# return inside the calldata. That check is what rejected every $0.19 leg on
# 2026-09-21 with "Min return not reached" while $0.22 legs went through
# minutes earlier — systematic, not price noise.
#
# The owner's protection does not come from this number: it comes from the
# contract's minOut, the per-leg dollar cap and the rate bound. Raising it
# gives the router room to fill a small leg; it does not widen what can be
# lost, which is still bounded by the cap.
SLIPPAGE_PERCENT = os.environ.get("VECTRA_SLIPPAGE_PERCENT", "1.0")
THROTTLE_S = 1.1
SANITY_BAND = 0.25           # reject a price 25% off the previous cycle

# The contract refuses a leg that moves more than maxLegBpsOfTarget of a
# token's target share count — in EITHER direction. A favourable fill legitimately
# delivers more than quoted, so a leg sized AT the bound is reverted by ordinary
# positive slippage, and the refusal log then shows a rate-limit breach on a
# trade that was simply better than expected. That works in testing and refuses
# every leg on a volatile day. Size beneath the ceiling, never against it.
RATE_HEADROOM = 0.80
# Sit UNDER the dollar bounds as well as the rate bound. A leg sized exactly at
# maxLegUsdc reverts if the contract's arithmetic rounds the other way, and a
# leg that reverts costs gas and records nothing.
LEG_HEADROOM = float(os.environ.get("VECTRA_LEG_HEADROOM", "0.95"))
# Sit under the TARGET as well as under the limits. The contract reverts
# Overshoot() on a leg that crosses it.
OVERSHOOT_HEADROOM = float(os.environ.get("VECTRA_OVERSHOOT_HEADROOM", "0.90"))
EXECUTE = os.environ.get("VECTRA_EXECUTE") == "1"
# Build and estimate the real transaction but stop before broadcasting.
DRY_SEND = os.environ.get("VECTRA_DRY_SEND") == "1"
MANDATE_ID = int(os.environ.get("VECTRA_MANDATE_ID") or 0)

# TWO KEEPERS, ONE KEY.
#
# The Render service and the Actions workflow can both be awake, both hold the
# same agent key, and both see the same mandate outside tolerance. Nothing in
# this process can see the other one: a lock in Python is a lock in ONE process,
# and GitHub's `concurrency:` group knows nothing about a container on Render.
#
# The chain is the only thing both can read, so the chain is the coordinator.
# Before sending, the agent asks how long ago THIS mandate last executed a leg,
# and defers if that is inside its gap. No lease, no database, no third service.
#
# Roles are asymmetric on purpose. The primary acts promptly; the fallback waits
# long enough that a living primary always beats it to the leg. Set
# VECTRA_ROLE=fallback on the host that is meant to be the understudy.
ROLE = (os.environ.get("VECTRA_ROLE") or "primary").strip().lower()
LEG_GAP_MIN = float(os.environ.get("VECTRA_MIN_LEG_GAP_MIN")
                    or (12 if ROLE == "fallback" else 4))

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


def load_mandate(mandate_id=None):
    """From chain when the contract is deployed; from file until then.

    The file form exists so the decision engine is exercisable before
    deployment. It is never a substitute for the on-chain mandate: when
    VECTRA_CONTRACT is set, chain state is the only source.
    """
    if CONTRACT:
        return load_mandate_from_chain(mandate_id)
    if not MANDATE_FILE.exists():
        raise SystemExit(f"No mandate at {MANDATE_FILE}")
    return json.loads(MANDATE_FILE.read_text())


# The contract exposes no getter for maxLegBpsOfTarget. It is fixed at creation
# and no function changes it, so it is configuration here rather than a chain
# read — but it IS a gap: every other bound the agent respects is read from the
# contract, and this one is asserted. SPEC 16 records it.
RATE_BPS_CONFIG = int(os.environ.get("VECTRA_RATE_BPS") or 0)


def load_mandate_from_chain(mandate_id=None):
    """The mandate as the CONTRACT holds it, not as a file describes it.

    Reading limits from a file while the contract enforces its own is how an
    agent ends up confidently proposing legs the chain refuses. Everything the
    contract exposes is read from it; symbols and decimals come from the tokens
    themselves.
    """
    from eth_abi import decode as abi_decode
    import xlayer as chain

    from eth_abi import encode as abi_encode
    from eth_utils import keccak

    def call(to, sig, types, *args):
        sel = keccak(text=sig)[:4]
        inner = sig[sig.index("(") + 1:sig.rindex(")")]
        arg_types = [t for t in inner.split(",") if t]
        data = "0x" + (sel + abi_encode(arg_types, list(args))).hex()
        res = chain.eth_call(to, data)
        if "error" in res:
            raise SystemExit(f"{sig} on {to}: {json.dumps(res['error'])[:200]}")
        return abi_decode(types, bytes.fromhex(res["result"][2:]))

    mandate_id = mandate_id or MANDATE_ID
    if not mandate_id:
        raise SystemExit("no mandate id given")

    (owner, agent, expiry, paused, revoked, drift_bps, max_leg, total_cap,
     spent, version) = call(
        CONTRACT, "mandate(uint256)",
        ["address", "address", "uint64", "bool", "bool", "uint16",
         "uint256", "uint256", "uint256", "uint64"],
        mandate_id)

    tokens, weights, targets = call(
        CONTRACT, "basket(uint256)", ["address[]", "uint16[]", "uint256[]"],
        mandate_id)

    if revoked:
        return None  # revoked: not an error, just nothing to service
    if paused:
        return None  # paused by its owner: respected, not an error

    rate_bps = RATE_BPS_CONFIG
    if not rate_bps:
        raise SystemExit(
            "VECTRA_RATE_BPS must be set: the contract exposes no getter for "
            "maxLegBpsOfTarget, and guessing the rate bound would mean sizing "
            "legs against a limit the agent cannot see.")

    # Symbols and decimals from the TOKENS, never a hardcoded map.
    basket = []
    for t, w, tg in zip(tokens, weights, targets):
        try:
            (sym,) = call(t, "symbol()", ["string"])
        except SystemExit:
            sym = f"{t[:6]}…{t[-4:]}"
        try:
            (dec,) = call(t, "decimals()", ["uint8"])
        except SystemExit:
            dec = 18
        basket.append({
            "symbol": sym,
            "address": t.lower(),
            "decimals": int(dec),
            "weightBps": int(w),
            "targetShares": int(tg),
        })

    return {
        "source": "chain",
        "mandateId": mandate_id,
        "owner": owner,
        "agent": agent,
        "expiry": int(expiry),
        "version": int(version),
        "driftToleranceBps": int(drift_bps),
        "maxLegUsdc": max_leg / 10 ** USDC_DECIMALS,
        "totalCapUsdc": total_cap / 10 ** USDC_DECIMALS,
        "spentUsdc": spent / 10 ** USDC_DECIMALS,
        "maxLegBpsOfTarget": rate_bps,
        "basket": basket,
    }


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


def gap_to_target_usd(p, direction):
    """How much room is left before the position REACHES its target, in dollars.

    The contract refuses a leg that overshoots — Overshoot() — because a
    rebalance that sails past the target has not converged, it has swapped one
    error for another. The agent was sizing legs in weight space while the
    contract checks share space, so once a position came within a leg's width
    of its target every proposal was refused and the keeper looped: on
    2026-09-22 NVDAx sat 0.00085 shares short while the agent kept offering
    0.00089, and every cycle reverted.

    Returned with headroom, because the fill is not known exactly in advance
    and landing a hair under the target is convergence while a hair over is a
    revert.
    """
    target = p.get("targetShares")
    held = p.get("shares")
    if target is None or held is None or not p.get("priceUsd"):
        return float("inf")
    remaining = (target - held) if direction == "buy" else (held - target)
    if remaining <= 0:
        return 0.0
    mult = p.get("multiplier") or 1.0
    tokens = remaining * mult / 10 ** p["decimals"]
    return tokens * p["priceUsd"] * OVERSHOOT_HEADROOM


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
        if not p["priceUsd"]:
            continue

        # OFF TARGET IS MEASURED IN SHARES, because that is what the mandate
        # states and what the contract enforces.
        #
        # This used to compare WEIGHT drift against the tolerance, and the
        # three layers disagreed: the contract holds share targets, the
        # interface shows the share gap, and the agent decided on weights.
        # Raising every target by 8% on 2026-09-22 moved the displayed distance
        # from 2.37% to 24.43% and moved the agent's input by nothing at all —
        # it sat idle with $0.53 unspent and every position 8% short, reporting
        # "within tolerance". An owner cannot amend a target the agent does not
        # look at.
        tgt = p.get("targetShares")
        held = p.get("shares")
        if not tgt or held is None:
            continue
        share_drift_bps = (held - tgt) / tgt * 10_000
        p["shareDriftBps"] = round(share_drift_bps, 2)
        if abs(share_drift_bps) <= tol:
            continue

        # The distance to close, in dollars, from the share gap rather than
        # from a weight difference.
        gap_usd = gap_to_target_usd(p, "buy" if share_drift_bps < 0 else "sell")

        # The contract's rate bound, expressed in dollars so it can be compared
        # with the other limits, and held under rather than met exactly.
        rate_usd = rate_cap_usd(m, p)

        # Every limit, named. The binding one is recorded rather than the
        # first one hit, because "why is the leg this size" and "what stopped
        # it being larger" are the same question and only the smallest limit
        # answers it.
        if share_drift_bps < 0:
            # Under target: buy with USDC. Spending consumes cap headroom.
            limits = {
                "drift gap": gap_usd,
                "maxLegUsdc": m["maxLegUsdc"] * LEG_HEADROOM,
                "remaining cap": remaining_cap * LEG_HEADROOM,
                "usdc on hand": state["usdcValueUsd"],
                "rate bound (maxLegBpsOfTarget)": rate_usd,
                "gap to target (shares)": gap_to_target_usd(p, "buy"),
            }
            direction, delta = "buy", +1
        else:
            # Over target: sell into USDC. A sell commits no new capital, so it
            # does not consume cap headroom — see SPEC 5.2 on the cap decision.
            limits = {
                "drift gap": gap_usd,
                "maxLegUsdc": m["maxLegUsdc"] * LEG_HEADROOM,
                "position value": p["valueUsd"] or 0,
                "rate bound (maxLegBpsOfTarget)": rate_usd,
                "gap to target (shares)": gap_to_target_usd(p, "sell"),
            }
            direction, delta = "sell", -1

        binding = min(limits, key=lambda k: limits[k])
        size = limits[binding]

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
            "shareDriftBps": p["shareDriftBps"],
            "distanceBefore": round(before, 2),
            "distanceAfter": round(after, 2),
            "reductionBps": round(before - after, 2),
            "bindingConstraint": binding,
            "limitsUsd": {k: round(v, 6) for k, v in limits.items()},
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

    def share_drift(p):
        tgt, held = p.get("targetShares"), p.get("shares")
        if not tgt or held is None:
            return 0.0
        return (held - tgt) / tgt * 10_000

    largest = max(priced, key=lambda p: abs(share_drift(p)))
    if abs(share_drift(largest)) <= tol:
        return None, (f"largest gap to target {abs(share_drift(largest)):.0f}bps "
                      f"is within tolerance {tol}bps, measured in shares")

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
            "shareDriftBps": best.get("shareDriftBps"),
            "bindingConstraint": best["bindingConstraint"],
            "limitsUsd": best["limitsUsd"],
            "rejected": candidates[1:],
            "reason": (f"{best['symbol']} is {abs(best['driftBps'])}bps "
                       f"{'below' if best['driftBps'] < 0 else 'above'} target; "
                       f"this leg cuts total distance from "
                       f"{best['distanceBefore']} to {best['distanceAfter']}bps"),
        }
        return leg, None

    # Nothing admissible. Name the binding constraint, not the first blocker.
    # In SHARE space, like every other decision here — this list used to be
    # built from weight drift, so once the agent moved to share targets it
    # reported "no admissible leg" with nothing named.
    under = [p for p in priced if share_drift(p) < -tol]
    over = [p for p in priced if share_drift(p) > tol]
    remaining_cap = m["totalCapUsdc"] - m["spentUsdc"]

    if remaining_cap <= 0 and under and not over:
        return None, (f"total spend cap reached "
                      f"(${m['spentUsdc']:.2f} of ${m['totalCapUsdc']:.2f}); "
                      f"buying is blocked and nothing is above target to sell")

    blockers = []
    for p in under:
        need = min(gap_to_target_usd(p, "buy"), m["maxLegUsdc"])
        if state["usdcValueUsd"] < 0.01:
            blockers.append(f"{p['symbol']} needs ~${need:.2f} but the owner "
                            f"holds no USDC")
        elif remaining_cap < 0.01:
            blockers.append(f"{p['symbol']} needs ~${need:.2f} but the spend "
                            f"cap has ${remaining_cap:.2f} left")
        else:
            blockers.append(f"{p['symbol']} leg sizes below the ${0.01:.2f} minimum")
    for p in over:
        blockers.append(f"{p['symbol']} is +{share_drift(p):.0f}bps above target "
                        f"but its sellable value is ${p['valueUsd'] or 0:.2f}")

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


def share_distance_bps(state):
    """Distance in SHARE space — the metric the interface shows and the chart
    plots, and the one that needs no prices.

    Sum over positions of |held - target| / target, in bps. Targets are held in
    shares, so this is the gap to the mandate as the CONTRACT states it, and a
    browser can compute it from chain reads alone.

    The agent decides on a WEIGHT-space distance instead, because choosing
    between legs requires comparing dollars and that requires prices. Both are
    recorded; only this one is displayed, because two numbers sharing one word
    is worse than either.
    """
    ps = state["positions"]
    if not ps:
        return None
    total = 0.0
    for p in ps:
        tgt = p.get("targetShares")
        held = p.get("shares")
        if not tgt or held is None:
            return None
        total += abs(held - tgt) / tgt * 10_000
    return round(total, 2)


def total_distance(state):
    """Total distance from target for the WHOLE basket, or None.

    None when any position could not be priced. A distance computed from the
    half of the basket that happened to quote is not a smaller distance, it is
    a different measurement wearing the same name — and on a chart it would
    read as convergence. The recorder makes the same choice with NA.
    """
    ps = state["positions"]
    if not ps or any(p["valueUsd"] is None for p in ps):
        return None
    values = [p["valueUsd"] for p in ps]
    targets = [p["targetWeightBps"] for p in ps]
    return round(distance_bps(values, state["totalUsd"], targets), 2)


def mandate_dir(mandate_id):
    """One directory per mandate.

    The agent services every active mandate, not one, so a single latest.json
    would be whichever mandate happened to run last — and the interface would
    show one owner the other's cycle. Each mandate's record is its own.
    """
    return LOG_DIR / str(mandate_id)


# Mandate 1's series, kept at the old path for the files already committed.
DISTANCE_CSV = LOG_DIR / "distance.csv"
DISTANCE_HEADER = ("ts_utc,status,distance_bps,total_usd,priced,positions,"
                   "leg_direction,leg_symbol,leg_usd,distance_after,"
                   "executed,tx_hash,binding_constraint,share_distance_bps\n")


def append_distance(started, state, leg, dist, execution=None,
                    share_dist=None, csv_path=None):
    """One row per cycle, appended, never rewritten.

    The archives are timestamped files and raw file hosting serves no directory
    listing, so a browser cannot walk them. This is the only shape the series
    can take that a page can actually read — and like the price record, it
    cannot be backfilled: a cycle that was not recorded when it happened is
    gone.
    """
    ps = state["positions"]
    priced = sum(1 for p in ps if p["valueUsd"] is not None)
    status = ("priced" if dist is not None
              else "partial" if priced else "no_price")
    row = ",".join(str(x) for x in [
        started.strftime("%Y-%m-%dT%H:%M:%SZ"),
        status,
        "NA" if dist is None else dist,
        round(state["totalUsd"], 2),
        priced,
        len(ps),
        leg["direction"] if leg else "",
        leg["symbol"] if leg else "",
        f"{leg['amountUsd']:.2f}" if leg else "",
        leg["distanceAfter"] if leg else "",
        # A SELECTED leg is not an EXECUTED one. These columns describe what
        # the agent chose; this one describes what actually happened, and only
        # a mined, successful transaction sets it.
        "true" if (execution or {}).get("executed") else "false",
        (execution or {}).get("txHash", "") or "",
        (leg or {}).get("bindingConstraint", "") or "",
        # The displayed metric. Needs no prices, so it is present even on a
        # cycle that could not quote — which is exactly when the weight-space
        # number is NA and the chart would otherwise have nothing to draw.
        "NA" if share_dist is None else share_dist,
    ]) + "\n"

    path = csv_path or DISTANCE_CSV
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(DISTANCE_HEADER)
    else:
        _migrate_header(path)
    with path.open("a") as fh:
        fh.write(row)
    return row.strip()


def _migrate_header(path=None):
    """Keep the header and the rows the same width.

    A column added to DISTANCE_HEADER does not reach a file that already
    exists, because the header is only written on creation. The rows then carry
    one more field than the header names, which is not an error anywhere — the
    file still parses, the last column is simply read under the wrong name or
    dropped. Silent, and the chart quietly plots something else.

    Existing rows are padded with an EMPTY value rather than a computed one:
    the measure did not exist when they were recorded, and inventing it now
    would be backfilling evidence."""
    path = path or DISTANCE_CSV
    lines = path.read_text().splitlines()
    if not lines:
        path.write_text(DISTANCE_HEADER)
        return
    want = DISTANCE_HEADER.strip().split(",")
    have = lines[0].split(",")
    if have == want:
        return
    if have != want[:len(have)]:
        print(f"    {path} header is not a prefix of the current one; "
              f"leaving it alone: {lines[0]}", file=sys.stderr)
        return
    pad = "," * (len(want) - len(have))
    out = [",".join(want)] + [ln + pad for ln in lines[1:] if ln.strip()]
    path.write_text("\n".join(out) + "\n")
    print(f"    {path} migrated: {len(have)} -> {len(want)} columns, "
          f"{len(out) - 1} existing row(s) padded", file=sys.stderr)


MINOUT_HAIRCUT_BPS = int(os.environ.get("VECTRA_MINOUT_HAIRCUT_BPS", "50"))
# How many times to requote when the router rejects its own minimum.
EXECUTE_ATTEMPTS = int(os.environ.get("VECTRA_EXECUTE_ATTEMPTS", "4"))


def seconds_since_last_leg(mandate_id):
    """Seconds since this mandate last emitted Executed, read from chain.

    Returns (age_seconds_or_None, scanned_ok). age None means no leg inside the
    window, which is the common case and is NOT an error.

    X Layer produces a block a second and REFUSES an eth_getLogs range wider
    than 100 blocks, so a single call sees only 100 seconds. The window is
    walked in chunks rather than asked for at once, because the wide query is
    refused rather than truncated and a swallowed refusal looks exactly like a
    chain with no legs on it.

    scanned_ok is returned separately so the caller can decide what an
    unanswered question means. It is not the same as "no leg found".
    """
    import xlayer as chain
    from eth_utils import keccak

    window_s = int(LEG_GAP_MIN * 60)
    topic0 = "0x" + keccak(
        text="Executed(uint256,address,address,uint256,uint256,uint64)").hex()
    topic1 = "0x" + f"{int(mandate_id):064x}"

    try:
        head = int(chain.rpc("eth_blockNumber", [])["result"], 16)
        # One second a block, so the window is about one block per second. A
        # margin is added because block time is an average, not a guarantee.
        lo = max(0, head - int(window_s * 1.5))
        newest = None
        b = head
        while b >= lo:
            a = max(lo, b - 94)
            r = chain.rpc("eth_getLogs", [{
                "address": CONTRACT, "fromBlock": hex(a), "toBlock": hex(b),
                "topics": [topic0, topic1]}])
            if "error" in r:
                return None, False
            for lg in r.get("result", []):
                n = int(lg["blockNumber"], 16)
                if newest is None or n > newest:
                    newest = n
            if newest is not None:
                break          # walking backwards: the first hit is the newest
            b = a - 1
        if newest is None:
            return None, True
        ts = int(chain.rpc("eth_getBlockByNumber",
                           [hex(newest), False])["result"]["timestamp"], 16)
        return max(0, int(time.time()) - ts), True
    except Exception:
        return None, False


def defer_to_other_keeper(mandate_id):
    """Whether to stand down this cycle. Returns a reason, or None to proceed.

    The fallback FAILS CLOSED and the primary FAILS OPEN when the chain cannot
    be read. An understudy that acts while blind is the thing this guard exists
    to prevent; a primary that stops whenever an RPC hiccups is a keeper that
    stops, which is worse than the race it was avoiding.
    """
    age, ok = seconds_since_last_leg(mandate_id)
    if not ok:
        if ROLE == "fallback":
            return ("could not read recent legs from chain and this host is the "
                    "fallback, so it defers rather than acting blind")
        return None
    if age is not None and age < LEG_GAP_MIN * 60:
        return (f"a leg for this mandate executed {age}s ago, inside this "
                f"host's {LEG_GAP_MIN:g} minute gap (role={ROLE}); another "
                f"keeper is servicing it")
    return None


def do_execute(m, leg, payload, payload_err):
    """Send the leg, or explain precisely why it was not sent.

    Returns a dict that ALWAYS says whether a transaction executed. A send that
    failed, reverted or was never attempted must never read as an execution —
    the distance series and the legs history are both built from this, and a
    cycle that claims a leg it did not take is worse than a cycle that did
    nothing.
    """
    import send as sender

    if not CONTRACT:
        return {"executed": False, "reason": "no contract configured"}
    mandate_id = m.get("mandateId") or MANDATE_ID
    if not mandate_id:
        return {"executed": False, "reason": "no mandate id configured"}
    if leg is None:
        return {"executed": False, "reason": "no leg selected this cycle"}
    if not payload:
        return {"executed": False, "reason": f"no payload: {payload_err}"}

    agent_addr = sender.agent_address()
    if not agent_addr:
        return {"executed": False, "reason": "no agent key available"}
    if agent_addr.lower() != (m.get("agent") or "").lower():
        # The mandate names one agent. Signing with anything else reverts
        # NotAgent, and spending gas to discover that is avoidable.
        return {"executed": False,
                "reason": f"key is {agent_addr}, mandate agent is {m.get('agent')}"}

    # Amount in the units of the token being SENT.
    if leg["direction"] == "buy":
        amount_in = int(round(leg["amountUsd"] * 10 ** USDC_DECIMALS))
    else:
        amount_in = int(round((leg["amountUsd"] / leg["priceUsd"])
                              * 10 ** leg["decimals"]))

    # minOut BELOW the quote, never equal to it. The quote already carries the
    # aggregator's slippage allowance; this sits under that, because a minOut
    # set exactly at the quoted figure reverts on any adverse rounding and a
    # revert costs gas and achieves nothing.
    quoted = int(payload.get("minReceiveAmount") or 0)
    if quoted <= 0:
        return {"executed": False, "reason": "quote carried no minReceiveAmount"}
    min_out = quoted * (10_000 - MINOUT_HAIRCUT_BPS) // 10_000
    if min_out <= 0:
        return {"executed": False, "reason": "minOut computed as zero"}

    print(f"\nSENDING: {leg['direction']} {leg['symbol']} "
          f"amountIn={amount_in} minOut={min_out} (quote {quoted}, "
          f"{MINOUT_HAIRCUT_BPS}bps under)")
    print(f"  route: {' | '.join(payload.get('routes') or [])}")

    # Retry with a FRESH quote when the router rejects its own minimum.
    #
    # Measured 2026-09-21: every failing leg routed through 'DYOR swap' and
    # every succeeding one through Uniswap V3, at sizes that all quote fine on
    # their own ($0.20 quotes at the same unit price as $2.00). The aggregator
    # sometimes returns a route whose quoted minReceive that route cannot
    # actually deliver, and the route differs between quotes — so asking again
    # is the fix, not a bigger slippage number, which was tried and did nothing.
    attempts = []
    result = err = None
    for attempt in range(1, EXECUTE_ATTEMPTS + 1):
        result, err = sender.send_execute(
            contract=CONTRACT, mandate_id=mandate_id,
            token_in=leg["tokenInAddress"], token_out=leg["tokenOutAddress"],
            amount_in=amount_in, min_out=min_out,
            router_calldata=payload["data"], sweep=[],
            dry_run=DRY_SEND,
        )
        attempts.append({"attempt": attempt,
                         "routes": payload.get("routes"),
                         "minOut": str(min_out),
                         "error": err})
        if not err or "Min return not reached" not in err:
            break
        if attempt == EXECUTE_ATTEMPTS:
            break
        print(f"  attempt {attempt} rejected by the router; requoting",
              file=sys.stderr)
        payload, payload_err = build_payload(leg)
        if not payload:
            err = f"requote failed: {payload_err}"
            break
        quoted = int(payload.get("minReceiveAmount") or 0)
        if quoted <= 0:
            err = "requote carried no minReceiveAmount"
            break
        min_out = quoted * (10_000 - MINOUT_HAIRCUT_BPS) // 10_000
        print(f"  requoted route: {' | '.join(payload.get('routes') or [])}")

    if err:
        print(f"  NOT SENT after {len(attempts)} attempt(s): {err}",
              file=sys.stderr)
        return {"executed": False, "reason": err, "amountIn": str(amount_in),
                "minOut": str(min_out), "attempts": attempts}
    if DRY_SEND:
        print(f"  DRY SEND ok, would use gas {result.get('gas')}")
        return {"executed": False, "reason": "dry send; not broadcast",
                "dryRun": result, "amountIn": str(amount_in),
                "minOut": str(min_out)}

    tx = result["txHash"]
    print(f"  sent {tx}")
    rcpt, rerr = sender.wait_for_receipt(tx)
    if rerr or not rcpt:
        return {"executed": False, "txHash": tx,
                "reason": f"sent but no receipt: {rerr}"}
    if rcpt["status"] != 1:
        print(f"  REVERTED in block {rcpt['blockNumber']}", file=sys.stderr)
        return {"executed": False, "txHash": tx, "reason": "transaction reverted",
                "receipt": rcpt}

    print(f"  MINED ok, block {rcpt['blockNumber']}, gas {rcpt['gasUsed']}")
    return {"executed": True, "txHash": tx, "receipt": rcpt,
            "amountIn": str(amount_in), "minOut": str(min_out),
            "routes": payload.get("routes"), "attempts": attempts}


def active_mandate_ids():
    """Every mandate the contract currently considers active.

    Read from chain rather than configured. A keeper told which mandate to
    service is a keeper that services exactly one — the owner who creates the
    second one gets a page that never changes and no explanation, because
    nothing is wrong anywhere except that nobody is looking at them.
    """
    from eth_abi import decode as abi_decode, encode as abi_encode
    from eth_utils import keccak
    import xlayer as chain

    def call(sig, types, *args):
        inner = sig[sig.index("(") + 1:sig.rindex(")")]
        data = "0x" + (keccak(text=sig)[:4]
                       + abi_encode([t for t in inner.split(",") if t],
                                    list(args))).hex()
        res = chain.eth_call(CONTRACT, data)
        if "error" in res:
            raise SystemExit(f"{sig}: {json.dumps(res['error'])[:200]}")
        return abi_decode(types, bytes.fromhex(res["result"][2:]))

    (next_id,) = call("nextMandateId()", ["uint256"])
    ids = []
    for i in range(1, int(next_id)):
        try:
            (ok,) = call("isActive(uint256)", ["bool"], i)
        except SystemExit:
            continue
        if ok:
            ids.append(i)
    return ids


def run_cycle(mandate_id=None):
    """One cycle for one mandate. Returns 0 on a cycle that ran."""
    m = load_mandate(mandate_id)
    if m is None:
        print(f"mandate {mandate_id}: paused or revoked, nothing to service")
        return 0
    started = now()
    print(f"cycle {started:%Y-%m-%d %H:%M:%S}Z   mandate "
          f"{m.get('mandateId', '-')}   owner {m['owner']}")
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

    # A STANDING limitation, not a refusal of this cycle.
    #
    # The issuer asks integrations to pause trading for a few minutes either
    # side of a multiplier activation, and those activation timestamps are not
    # published anywhere this agent can read (SPEC 16). So the agent does not
    # pause: legs continue straight through those windows.
    #
    # It is recorded on every cycle because it is true on every cycle, and it
    # appears alongside cycles that executed because those cycles DID execute
    # without the pause. Wording it as a failure would be wrong twice over —
    # nothing failed, and what is actually declined is the pause itself.
    state["refusals"].append({
        "token": "*",
        "standing": True,
        "reason": "Does not pause around rebase activation. The issuer asks "
                  "integrations to halt briefly either side of a multiplier "
                  "activation; those timestamps are not published anywhere "
                  "readable, so legs run through those windows rather than "
                  "waiting them out. Standing limitation, not a refusal of "
                  "this cycle (SPEC 14, open item)."})

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

    execution = None
    if EXECUTE:
        # Asked of the CHAIN, not of a local file: the published cycle log is
        # committed every few cycles and is stale by minutes, which would make
        # this either useless or permanently over-cautious.
        standdown = defer_to_other_keeper(mid) if mid else None
        if standdown:
            print(f"\nSTAND DOWN: {standdown}")
            leg = None
            execution = {"sent": False, "reason": standdown,
                         "deferred": True, "role": ROLE}
        else:
            execution = do_execute(m, leg, payload, payload_err)

    mid = m.get("mandateId")
    # Mandate 1 keeps the historical paths so the files already committed and
    # already fetched by the interface do not move; every other mandate gets
    # its own directory.
    outdir = LOG_DIR if mid in (1, None) else mandate_dir(mid)
    outdir.mkdir(parents=True, exist_ok=True)
    out = outdir / f"cycle_{started:%Y%m%dT%H%M%S}Z.json"
    payload_json = json.dumps({
        "ts": started.isoformat(timespec="seconds"),
        "mode": "execute" if EXECUTE else "dry-run",
        "mandateId": mid,
        "owner": m["owner"], "contract": CONTRACT or None,
        "totalUsd": state["totalUsd"], "usdcValueUsd": state["usdcValueUsd"],
        "positions": state["positions"],
        "leg": leg, "noActionReason": why_not,
        "payload": payload, "payloadError": payload_err,
        "slippagePercent": SLIPPAGE_PERCENT,
        "minOutHaircutBps": MINOUT_HAIRCUT_BPS,
        "execution": execution,
        "refusals": state["refusals"],
    }, indent=2) + "\n"

    out.write_text(payload_json)

    # Also written to a STABLE path. The timestamped file is the archive; this
    # is what a browser can actually fetch, because raw file hosting serves
    # files and not directory listings, so a timestamped name is unreachable
    # without an index. The interface's next-move panel and refusal log both
    # depend on this, and its `ts` field is what lets the interface tell a
    # stopped agent from a stable position.
    (outdir / "latest.json").write_text(payload_json)

    dist = total_distance(state)
    print("\ndistance " + ("NA (not every position priced)" if dist is None
                            else f"{dist}bps"))
    share_dist = share_distance_bps(state)
    print(f"share-space distance {share_dist}bps (the displayed metric)")
    print("series += " + append_distance(
        started, state, leg, dist, execution, share_dist,
        csv_path=(DISTANCE_CSV if mid in (1, None)
                  else outdir / "distance.csv")))

    print(f"\nlogged {out} and {outdir / 'latest.json'}")
    return 0


def main():
    """Service every active mandate, one cycle each.

    A failure on one mandate must not stop the others: they are different
    owners, and one bad quote is not a reason to leave everybody else's
    position unattended.
    """
    if not CONTRACT:
        return run_cycle()          # file-backed dry run, pre-deployment

    ids = active_mandate_ids()
    if not ids:
        print("no active mandates on this contract")
        return 0

    print(f"servicing {len(ids)} active mandate(s): "
          f"{', '.join(str(i) for i in ids)}\n")
    failures = 0
    for i in ids:
        print(f"{'=' * 60}\nMANDATE {i}")
        try:
            run_cycle(i)
        except SystemExit as e:
            failures += 1
            print(f"mandate {i} cycle failed: {e}", file=sys.stderr)
        except Exception as e:
            failures += 1
            print(f"mandate {i} cycle failed: {e!r}", file=sys.stderr)
    return 1 if failures == len(ids) else 0


if __name__ == "__main__":
    raise SystemExit(main())
