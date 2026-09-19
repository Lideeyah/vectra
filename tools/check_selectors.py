"""Verify every hand-encoded function selector against its signature.

The frontend's ABI had two struct fields transposed, which changed a selector
and made every call hit no function at all. It survived because Solidity
initialises structs by name while an ABI is positional, so everything that
stayed on one side of that boundary agreed with itself.

The agent is a positional caller too: it builds calldata from hex selectors
written by hand. Those are the same exposure, so they are checked rather than
trusted. A wrong selector here would not raise — it would read zero, or call
something else entirely.
"""

import re
import sys
from pathlib import Path

try:
    from eth_hash.auto import keccak
except ImportError:
    print("eth-hash is required: pip install eth-hash[pycryptodome]", file=sys.stderr)
    raise SystemExit(2)


def selector(sig: str) -> str:
    return "0x" + keccak(sig.encode())[:4].hex()


# Every hand-encoded selector in the repository, with the signature it claims.
CLAIMS = [
    ("agent.py", "SEL_BALANCE_OF", "0x70a08231", "balanceOf(address)"),
    ("agent.py", "SEL_ALLOWANCE", "0xdd62ed3e", "allowance(address,address)"),
    ("agent.py", "sharesOf inline", "0xf5eb42dc", "sharesOf(address)"),
    ("xlayer.py", "SEL_MULTIPLIER", "0x1b3ed722", "multiplier()"),
    ("xlayer.py", "SEL_DECIMALS", "0x313ce567", "decimals()"),
    ("xlayer.py", "SEL_SYMBOL", "0x95d89b41", "symbol()"),
]


def main() -> int:
    bad = 0
    print(f"{'FILE':<12} {'NAME':<18} {'CLAIMED':<12} {'ACTUAL':<12} SIGNATURE")
    for file, name, claimed, sig in CLAIMS:
        actual = selector(sig)
        ok = actual == claimed
        if not ok:
            bad += 1
        print(f"{'ok  ' if ok else 'FAIL'} {file:<8}{name:<18} {claimed:<12} {actual:<12} {sig}")

    # And confirm the constants are still present with those values, so a
    # renamed or edited constant cannot silently drop out of this check.
    for file, name, claimed, _ in CLAIMS:
        text = Path(file).read_text()
        if claimed not in text:
            print(f"FAIL {file}: {claimed} ({name}) no longer appears — check is stale")
            bad += 1

    print(f"\n{'PASS' if bad == 0 else f'FAIL ({bad})'} — {len(CLAIMS)} selectors checked")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
