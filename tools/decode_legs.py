"""Decode raw Executed / TargetsSet logs into the shape the interface reads.

This runs over `cast logs --json` output. Nothing about it is development-only:
the logs an anvil fork produces and the logs mainnet produces are the same
bytes, so the decoder that reads one reads the other unchanged. That is the
whole reason the dev leg exists — to get real event data of the mainnet shape
before the mainnet mandate is funded.

Hand-rolled ABI decoding rather than a dependency: the two event shapes are
fixed and small, and a decoder whose behaviour is visible here is easier to
trust than one whose version drifts.

Usage:  python tools/decode_legs.py data/dev
"""

import json
import pathlib
import sys

# Both computed with `cast sig-event`, and asserted against the exported logs
# rather than trusted: a topic that silently fails to match is indistinguishable
# from a run in which nothing happened.
EXECUTED_TOPIC = "0x07756c6d892d68f0b0dd3980b163756c2bc71fe5e4fe2374adde063dd216decc"


def _words(data: str):
    """Split `0x...` calldata into 32-byte words as ints and raw hex."""
    b = bytes.fromhex(data[2:] if data.startswith("0x") else data)
    return [b[i:i + 32] for i in range(0, len(b), 32)]


def _uint(word: bytes) -> int:
    return int.from_bytes(word, "big")


def _addr(word: bytes) -> str:
    return "0x" + word[-20:].hex()


def _array(b: bytes, offset: int):
    """Read a uint256[] whose tail begins at `offset` bytes into `b`."""
    n = int.from_bytes(b[offset:offset + 32], "big")
    return [
        str(int.from_bytes(b[offset + 32 + i * 32: offset + 64 + i * 32], "big"))
        for i in range(n)
    ]


def decode_executed(log: dict) -> dict:
    """Executed(uint256 indexed id, address tokenIn, address tokenOut,
                uint256 amountIn, uint256 amountOut, uint64 version)"""
    w = _words(log["data"])
    if len(w) != 5:
        raise ValueError(f"Executed data has {len(w)} words, expected 5")
    return {
        "id": str(int(log["topics"][1], 16)),
        "tokenIn": _addr(w[0]),
        "tokenOut": _addr(w[1]),
        "amountIn": str(_uint(w[2])),
        "amountOut": str(_uint(w[3])),
        "version": _uint(w[4]),
        "txHash": log["transactionHash"],
        "blockNumber": int(log["blockNumber"], 16),
        "timestamp": int(log["blockTimestamp"], 16) if log.get("blockTimestamp") else None,
    }


def decode_targets_set(log: dict) -> dict:
    """TargetsSet(uint256 indexed id, uint256[] previous, uint256[] current,
                  uint64 version, uint256 timestamp)

    Two dynamic arrays, so the head holds offsets and the values live in tails.
    """
    b = bytes.fromhex(log["data"][2:])
    off_prev = int.from_bytes(b[0:32], "big")
    off_cur = int.from_bytes(b[32:64], "big")
    return {
        "id": str(int(log["topics"][1], 16)),
        "previous": _array(b, off_prev),
        "current": _array(b, off_cur),
        "version": int.from_bytes(b[64:96], "big"),
        "timestamp": int.from_bytes(b[96:128], "big"),
        "txHash": log["transactionHash"],
        "blockNumber": int(log["blockNumber"], 16),
    }


def main(argv):
    d = pathlib.Path(argv[1] if len(argv) > 1 else "data/dev")

    def load(name):
        p = d / f"{name}.json"
        if not p.exists():
            return []
        text = p.read_text().strip()
        return json.loads(text) if text else []

    raw_exec = load("executed")
    raw_targets = load("targets_set")

    # The topic is checked, not assumed. A mismatch here means the exporter
    # queried for one event and the contract emitted another, which would
    # otherwise look exactly like a quiet run.
    for log in raw_exec:
        if log["topics"][0].lower() != EXECUTED_TOPIC:
            raise SystemExit(
                f"topic mismatch: exported {log['topics'][0]}, "
                f"Executed is {EXECUTED_TOPIC}"
            )

    legs = [decode_executed(l) for l in raw_exec]
    legs.sort(key=lambda r: (r["blockNumber"], r["txHash"]))
    amendments = [decode_targets_set(l) for l in raw_targets]
    amendments.sort(key=lambda r: r["blockNumber"])

    out = {
        "source": "anvil fork of X Layer, real OKX router — development data",
        "legs": legs,
        "amendments": amendments,
    }
    (d / "history.json").write_text(json.dumps(out, indent=2) + "\n")

    print(f"decoded {len(legs)} leg(s), {len(amendments)} amendment(s) -> {d}/history.json")
    for leg in legs:
        print(f"  mandate {leg['id']}  {leg['amountIn']} {leg['tokenIn'][:10]}"
              f" -> {leg['amountOut']} {leg['tokenOut'][:10]}  v{leg['version']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
