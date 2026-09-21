"""Export the contract's own events from X Layer into data/history.json.

X Layer caps eth_getLogs at a 100-block range, so this walks the chain in
chunks from the deployment block rather than asking for everything at once —
the wide query is REFUSED, not merely slow, and a refusal that gets swallowed
looks exactly like a chain with no events on it.

Writes the mainnet file the interface prefers. data/dev/history.json stays
where it is and is never read by a production build.

Usage:  python3 tools/export_mainnet_history.py
"""

import json
import os
import pathlib
import subprocess
import sys

RPC = os.environ.get("VECTRA_RPC", "https://rpc.xlayer.tech")
CONTRACT = os.environ.get("VECTRA_CONTRACT",
                          "0x08Ed8562e2fD44C82EBA0CDfbC6F5Fdca3Cf19a0")
DEPLOY_BLOCK = int(os.environ.get("VECTRA_DEPLOY_BLOCK", "71216017"))
CHUNK = 95           # under X Layer's 100-block ceiling

EXECUTED = "Executed(uint256,address,address,uint256,uint256,uint64)"
TARGETS_SET = "TargetsSet(uint256,uint256[],uint256[],uint64,uint256)"


def sh(*args):
    r = subprocess.run(args, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"{' '.join(args[:3])}…: {r.stderr.strip()[:200]}")
    return r.stdout.strip()


def scan(sig):
    topic = sh("cast", "sig-event", sig)
    head = int(sh("cast", "block-number", "--rpc-url", RPC))
    out, b = [], DEPLOY_BLOCK
    while b <= head:
        e = min(b + CHUNK - 1, head)
        raw = sh("cast", "logs", topic, "--address", CONTRACT,
                 "--from-block", str(b), "--to-block", str(e),
                 "--rpc-url", RPC, "--json")
        try:
            out.extend(json.loads(raw or "[]"))
        except json.JSONDecodeError:
            raise SystemExit(f"unparseable log response for blocks {b}-{e}")
        b = e + 1
    print(f"  {sig.split('(')[0]}: {len(out)} event(s) over blocks "
          f"{DEPLOY_BLOCK}-{head}")
    return out


def main():
    d = pathlib.Path("data")
    d.mkdir(exist_ok=True)
    print(f"scanning {CONTRACT} on {RPC}")
    (d / "executed.json").write_text(json.dumps(scan(EXECUTED)))
    (d / "targets_set.json").write_text(json.dumps(scan(TARGETS_SET)))

    # Same decoder the fork export uses. The bytes are identical; only the
    # origin differs, and that is what decides whether the interface links a
    # hash to the explorer. Called explicitly — importing it runs nothing,
    # because it guards on __main__.
    import decode_legs
    return decode_legs.main(["decode_legs", "data", "mainnet"])


if __name__ == "__main__":
    sys.path.insert(0, str(pathlib.Path(__file__).parent))
    raise SystemExit(main())
