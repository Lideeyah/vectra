"""The distance series, and the rule that a partial measurement is not one.

The agent's live path cannot be exercised from this machine — OKX is
unreachable here, which is why the recorder and the agent run in Actions. So
the arithmetic and the NA rule are tested directly against constructed state,
where a half-priced basket can be produced on demand rather than waited for.

The rule under test: if any position failed to price, the cycle records NA, not
a number. A distance computed from the positions that happened to quote is
smaller than the real one, and on a chart it reads as convergence — the product
claiming progress it did not make, at exactly the moment it knows least.

Run:  python3 test_distance_series.py
"""

import os
import pathlib
import tempfile

os.environ["VECTRA_LOG_DIR"] = tempfile.mkdtemp(prefix="vectra-distance-")

import agent  # noqa: E402

failures = 0


def check(name, actual, expected):
    global failures
    ok = str(actual) == str(expected)
    if not ok:
        failures += 1
    print(f"  {'ok  ' if ok else 'FAIL'} {name:<44} got={actual} want={expected}")


def state(values, targets, total=None):
    """Minimal state of the shape build_state returns. None value = unpriced."""
    return {
        "positions": [
            {"symbol": f"T{i}", "valueUsd": v, "targetWeightBps": t}
            for i, (v, t) in enumerate(zip(values, targets))
        ],
        "totalUsd": sum(v for v in values if v is not None) if total is None else total,
    }


print("distance arithmetic")
# Exactly on target: two positions, 50/50, equal value.
check("perfectly balanced is 0bps",
      agent.total_distance(state([50.0, 50.0], [5000, 5000])), 0.0)

# 60/40 against a 50/50 target: each side is 1000bps out, L1 sum is 2000.
check("60/40 against 50/50 is 2000bps",
      agent.total_distance(state([60.0, 40.0], [5000, 5000])), 2000.0)

print("\nthe NA rule")
check("one position unpriced -> None",
      agent.total_distance(state([60.0, None], [5000, 5000], total=60.0)), None)
check("all positions unpriced -> None",
      agent.total_distance(state([None, None], [5000, 5000], total=0.0)), None)
check("empty basket -> None", agent.total_distance(state([], [])), None)

# The failure this rule exists to prevent, as a test rather than a comment.
#
# If T1 could be priced at 50.0 the basket would be exactly on target: 0bps.
# Dropping it and measuring the rest reports 5000bps, because the surviving
# position is then 100% of a total it should be half of, while the target
# weights still sum to 10000. So a partial measurement is not a slightly worse
# reading of the same thing — here it turns a perfectly balanced basket into
# maximal divergence. Which direction it errs in is not the point; that it
# produces a confident number for a cycle that could not be measured is.
half = state([50.0, None], [5000, 5000], total=50.0)
naive = agent.distance_bps([50.0], half["totalUsd"], [5000])
whole = agent.total_distance(state([50.0, 50.0], [5000, 5000]))
check("the basket, fully priced, is on target", whole, 0.0)
check("the priced half alone claims 5000bps", naive, 5000.0)
check("...so the cycle records NA instead", agent.total_distance(half), None)

print("\nrows written")
out = pathlib.Path(os.environ["VECTRA_LOG_DIR"])
import datetime  # noqa: E402

ts = datetime.datetime(2026, 9, 19, 12, 0, 0)

s1 = state([60.0, 40.0], [5000, 5000])
agent.append_distance(ts, s1, None, agent.total_distance(s1))

leg = {"direction": "sell", "symbol": "T0", "amountUsd": 5.0, "distanceAfter": 400.0}
s2 = state([60.0, 40.0], [5000, 5000])
agent.append_distance(ts, s2, leg, agent.total_distance(s2))

s3 = state([50.0, None], [5000, 5000], total=50.0)
agent.append_distance(ts, s3, None, agent.total_distance(s3))

# A leg that was SELECTED but not EXECUTED must not read as executed. This is
# the distinction the legs history and the distance chart are both built on.
s4 = state([60.0, 40.0], [5000, 5000])
agent.append_distance(ts, s4, leg, agent.total_distance(s4),
                      execution={"executed": False, "reason": "reverted"})
s5 = state([60.0, 40.0], [5000, 5000])
agent.append_distance(ts, s5, leg, agent.total_distance(s5),
                      execution={"executed": True, "txHash": "0xabc"})

lines = (out / "distance.csv").read_text().strip().split("\n")
check("header written once", lines[0].startswith("ts_utc,status,distance_bps"), True)
check("five rows appended", len(lines) - 1, 5)
check("priced row carries the number", lines[1].split(",")[2], "2000.0")
check("leg row carries the leg", ",".join(lines[2].split(",")[6:9]), "sell,T0,5.00")
check("partial row carries NA", lines[3].split(",")[1:3], "['partial', 'NA']")

print("\nselected is not executed")
head = lines[0].split(",")
ex_i, tx_i = head.index("executed"), head.index("tx_hash")
check("a leg with no execution is not executed", lines[1].split(",")[ex_i], "false")
check("a FAILED send is not executed", lines[4].split(",")[ex_i], "false")
check("...and records no tx hash", lines[4].split(",")[tx_i], "")
check("a mined send IS executed", lines[5].split(",")[ex_i], "true")
check("...and records its hash", lines[5].split(",")[tx_i], "0xabc")

print(f"\n{'ALL PASS' if failures == 0 else f'{failures} FAILURE(S)'}")
raise SystemExit(1 if failures else 0)
