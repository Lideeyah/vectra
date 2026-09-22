"""Leg selection tests. Pure decision logic — no network, no chain.

Run: python test_agent_selection.py
"""

import agent

TOL = 500


def mandate(cap=50.0, spent=0.0, max_leg=5.0, rate_bps=2000):
    return {"driftToleranceBps": TOL, "maxLegUsdc": max_leg,
            "totalCapUsdc": cap, "spentUsdc": spent, "owner": "0x0",
            "maxLegBpsOfTarget": rate_bps, "basket": []}


def position(sym, value, target, price=100.0, target_shares=None):
    return {"symbol": sym, "address": "0x" + sym.encode().hex().ljust(40, "0")[:40],
            "decimals": 18, "priceUsd": price, "valueUsd": value,
            "targetWeightBps": target, "targetShares": target_shares,
            "multiplier": 1.0}


def state(positions, usdc):
    total = sum(p["valueUsd"] for p in positions) + usdc
    for p in positions:
        p["actualWeightBps"] = int(round(p["valueUsd"] / total * 10_000))
        p["driftBps"] = p["actualWeightBps"] - p["targetWeightBps"]
        # Shares held, derived from the value so the two spaces describe the
        # same position. The agent decides on the SHARE gap — that is what the
        # mandate states and what the contract enforces — so a fixture without
        # shares would exercise nothing.
        p["shares"] = int(p["valueUsd"] / p["priceUsd"]
                          * 10 ** p["decimals"] / (p["multiplier"] or 1))
        # Target shares that MEAN the same thing as the target weight, unless a
        # test states its own. A fixture whose share target and weight target
        # describe different positions tests neither.
        if p.get("targetShares") is None:
            p["targetShares"] = int(p["targetWeightBps"] / 10_000 * total
                                    / p["priceUsd"] * 10 ** p["decimals"]
                                    / (p["multiplier"] or 1))
    return {"positions": positions, "usdcValueUsd": usdc, "totalUsd": total,
            "investedUsd": total - usdc, "usdcBalance": int(usdc * 1e6),
            "refusals": []}


def show(title, s, leg, why):
    print(f"\n=== {title}")
    print(f"  total ${s['totalUsd']:.2f}   cash ${s['usdcValueUsd']:.2f}   "
          f"distance {s.get('distanceBefore')}bps")
    for p in s["positions"]:
        print(f"    {p['symbol']:<6} ${p['valueUsd']:>8.2f}  "
              f"{p['actualWeightBps']:>5}b vs {p['targetWeightBps']:>5}b  "
              f"drift {p['driftBps']:>+6}b")
    for c in s.get("candidates", []):
        print(f"    candidate {c['direction']:<4} {c['symbol']:<6} "
              f"${c['amountUsd']:>6.2f} -> {c['distanceAfter']:>8}bps "
              f"(cuts {c['reductionBps']}bps)")
    print(f"  => {leg['direction'].upper() + ' ' + leg['symbol'] if leg else 'NO LEG'}")
    if why:
        print(f"     {why}")


def test_picks_largest_reduction_across_directions():
    """A sell and a buy are both admissible; the bigger cut must win."""
    # A is far overweight, B mildly underweight. Cash is available, so both a
    # buy of B and a sell of A are admissible.
    # Cash is limited to $2, so the buy can only be sized at $2 while the sell
    # can use the full $5 leg limit. The cuts are therefore unequal and the
    # choice is a real comparison rather than a tie.
    s = state([position("AAAx", 700.0, 4000), position("BBBx", 200.0, 6000)], usdc=2.0)
    m = mandate()
    leg, why = agent.select_leg(m, s)
    show("competing legs, both directions admissible", s, leg, why)

    assert leg is not None, why
    assert len(s["candidates"]) >= 2, "expected competing candidates"
    best = s["candidates"][0]
    for other in s["candidates"][1:]:
        assert best["reductionBps"] >= other["reductionBps"], "not the largest cut"
    assert leg["symbol"] == best["symbol"] and leg["direction"] == best["direction"]
    assert best["reductionBps"] > s["candidates"][1]["reductionBps"], \
        "the comparison must be strict, not a tie"
    assert leg["rejected"], "the rejected alternative must be recorded"
    print("  PASS: chose the largest distance reduction, alternative recorded")


def test_sells_when_no_cash():
    """The case the buy-only agent could not handle at all."""
    s = state([position("AAAx", 900.0, 3400), position("BBBx", 0.0, 6600)], usdc=0.0)
    leg, why = agent.select_leg(mandate(), s)
    show("overweight, zero cash — buy-only could not act", s, leg, why)
    assert leg is not None, why
    assert leg["direction"] == "sell" and leg["symbol"] == "AAAx"
    print("  PASS: converges from an overweight position with no cash")


def test_within_tolerance_does_nothing():
    s = state([position("AAAx", 505.0, 5000), position("BBBx", 495.0, 5000)], usdc=0.0)
    leg, why = agent.select_leg(mandate(), s)
    show("inside tolerance", s, leg, why)
    assert leg is None and "within tolerance" in why
    print("  PASS: no action inside tolerance")


def test_cap_blocks_buy_but_not_sell():
    """The cap bounds committed capital, so it must not block a sell."""
    s = state([position("AAAx", 900.0, 3400), position("BBBx", 100.0, 6600)], usdc=50.0)
    m = mandate(cap=10.0, spent=10.0)   # no headroom left
    leg, why = agent.select_leg(m, s)
    show("cap exhausted", s, leg, why)
    assert leg is not None, why
    assert leg["direction"] == "sell", "a sell must remain available under a full cap"
    assert all(c["direction"] == "sell" for c in s["candidates"]), \
        "a buy must not be offered with no cap headroom"
    print("  PASS: cap blocks buying, sell still available")


def test_refusal_names_the_binding_constraint():
    """Underweight, no cash, nothing sellable: say which, and how much."""
    s = state([position("AAAx", 100.0, 5000), position("BBBx", 100.0, 5000)], usdc=0.0)
    # Force the gap in SHARES, which is the space the agent decides in. Setting
    # driftBps here used to do it; once the agent moved to share targets that
    # line changed nothing and the test was asserting against a position the
    # agent considered already on target.
    s["positions"][0]["shares"] = int(s["positions"][0]["targetShares"] * 0.70)
    s["positions"][1]["shares"] = s["positions"][1]["targetShares"]
    leg, why = agent.select_leg(mandate(), s)
    show("underweight with no funding", s, leg, why)
    assert leg is None
    assert "no USDC" in why and "AAAx" in why, why
    assert "buy-only" not in why, "stale buy-only wording must be gone"
    print("  PASS: refusal names the token, the amount and the real blocker")


def test_leg_is_sized_under_the_rate_bound_not_against_it():
    """A leg sized AT the contract's ceiling is reverted by a favourable fill.

    The contract permits maxLegBpsOfTarget of target shares in either direction,
    so ordinary positive slippage on a leg sized exactly at the bound trips it,
    and the refusal log shows a rate-limit breach on a trade that was merely
    better than expected. The agent must stay beneath the ceiling.
    """
    s = state([position("AAAx", 100.0, 9000), position("BBBx", 900.0, 1000)], usdc=500.0)
    m = mandate(cap=10_000.0, max_leg=1_000.0)
    leg, why = agent.select_leg(m, s)
    show("rate bound with headroom", s, leg, why)

    assert leg is not None, why

    # The ceiling is COMPUTED from the position the fixture actually describes,
    # not written down. It used to be a hardcoded $200 that matched a fixed
    # share target; once targets were derived from the weight target that
    # number silently described a different position, and the test would have
    # failed for being stale rather than for the agent being wrong.
    chosen = next(p for p in s["positions"] if p["symbol"] == leg["symbol"])
    ceiling = (chosen["targetShares"] * m["maxLegBpsOfTarget"] / 10_000
               * (chosen["multiplier"] or 1) / 10 ** chosen["decimals"]
               * chosen["priceUsd"])
    assert leg["amountUsd"] <= ceiling * agent.RATE_HEADROOM + 1e-9, \
        f"leg sized at {leg['amountUsd']}, must stay under {ceiling}"
    assert leg["amountUsd"] < ceiling, "no headroom beneath the ceiling"
    print(f"  PASS: leg ${leg['amountUsd']:.2f} sits under the ${ceiling:.2f} ceiling "
          f"({agent.RATE_HEADROOM:.0%} headroom)")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print(f"\n{len(tests)} selection tests passed")
