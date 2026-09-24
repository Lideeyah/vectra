"""Check the two-keeper stand-down guard, against the real chain.

    python3 tools/check_standdown.py

Nothing is signed and nothing is sent: VECTRA_AGENT_KEY is never read here.

Three things are checked, because each can pass while another fails:

  1. The log filter finds a REAL leg when pointed at the block that holds one.
     This is the part that talks to the chain, and a broken topic filter would
     silently find nothing and read as "no recent leg, go ahead".

  2. The live window answers at all, and how long it takes. The scan is walked
     in chunks because X Layer refuses wide ranges, so its cost grows with the
     configured gap.

  3. Every branch of the decision, including the asymmetry: the primary fails
     OPEN when the chain cannot be read, the fallback fails CLOSED.
"""
import os, pathlib, sys, time

# Run from tools/ or from the root; the agent lives at the root either way.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

os.environ.setdefault("VECTRA_CONTRACT",
                      "0x08Ed8562e2fD44C82EBA0CDfbC6F5Fdca3Cf19a0")
import agent
import xlayer as chain
from eth_utils import keccak

# A leg that is on X Layer and is not going anywhere.
KNOWN_BLOCK = 71297817
fails = []

print(f"contract {agent.CONTRACT}")
print(f"role     {agent.ROLE}   gap {agent.LEG_GAP_MIN:g} min\n")

# 1 ---------------------------------------------------------------- the filter
t0 = "0x" + keccak(
    text="Executed(uint256,address,address,uint256,uint256,uint64)").hex()
r = chain.rpc("eth_getLogs", [{
    "address": agent.CONTRACT,
    "fromBlock": hex(KNOWN_BLOCK - 5), "toBlock": hex(KNOWN_BLOCK + 5),
    "topics": [t0, "0x" + f"{1:064x}"]}])
hits = [int(l["blockNumber"], 16) for l in r.get("result", [])]
ok = KNOWN_BLOCK in hits
print(f"1. filter finds the known leg at {KNOWN_BLOCK}: "
      f"{'PASS' if ok else 'FAIL'}  (matched {hits})")
if not ok:
    fails.append("the Executed filter did not match a leg that exists")

# 2 ----------------------------------------------------------- the live window
t = time.time()
age, scanned = agent.seconds_since_last_leg(1)
dt = time.time() - t
print(f"2. live {agent.LEG_GAP_MIN:g} min window: scanned={scanned} "
      f"age={age}  ({dt:.1f}s)")
if not scanned:
    fails.append("the live scan could not complete")

# 3 --------------------------------------------------------------- the branches
real = agent.seconds_since_last_leg
cases = [
    ("leg 30s ago",            (30, True),   "primary",  True),
    ("leg just outside gap",   (int(agent.LEG_GAP_MIN * 60) + 60, True),
                                             "primary",  False),
    ("no leg in window",       (None, True), "primary",  False),
    ("scan failed, primary",   (None, False), "primary", False),
    ("scan failed, fallback",  (None, False), "fallback", True),
]
print("3. decision branches")
for label, ret, role, want_defer in cases:
    agent.seconds_since_last_leg = lambda _mid, _r=ret: _r
    agent.ROLE = role
    got = agent.defer_to_other_keeper(1) is not None
    mark = "PASS" if got == want_defer else "FAIL"
    print(f"   {mark}  {label:24s} role={role:8s} "
          f"-> {'DEFER' if got else 'proceed'}")
    if got != want_defer:
        fails.append(f"{label} as {role}: expected "
                     f"{'DEFER' if want_defer else 'proceed'}")
agent.seconds_since_last_leg = real

print()
if fails:
    for f in fails:
        print("FAIL:", f)
    sys.exit(1)
print("stand-down guard OK")
