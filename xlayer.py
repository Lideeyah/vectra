"""X Layer RPC reads. Stdlib only. eth_call is read-only — nothing here can send a transaction."""

import json
import urllib.request

RPC = "https://rpc.xlayer.tech"

# Verified live against NVDAx (0xc845b2...49d) on X Layer: multiplier() returns
# an 18-decimal fixed-point value. getMultiplier(), currentMultiplier(),
# scalingFactor() and totalShares() all revert on that contract.
SEL_MULTIPLIER = "0x1b3ed722"
SEL_DECIMALS = "0x313ce567"
SEL_SYMBOL = "0x95d89b41"

MULTIPLIER_SCALE = 10 ** 18


def eth_call(to, data, timeout=20):
    payload = {"jsonrpc": "2.0", "method": "eth_call",
               "params": [{"to": to, "data": data}, "latest"], "id": 1}
    req = urllib.request.Request(
        RPC, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def multiplier(address):
    """(scaled_float, raw_int) or (None, None) with the reason discarded by caller.

    A sane multiplier sits near 1.0. The NVDAx proxy returns padded garbage for
    some unknown selectors, so anything absurd is rejected rather than recorded.
    """
    try:
        res = eth_call(address, SEL_MULTIPLIER)
    except Exception:
        return None, None
    if "error" in res:
        return None, None
    raw = res.get("result") or "0x"
    if raw in ("0x", ""):
        return None, None
    # A correct uint256 return is exactly 32 bytes; longer means returndata bleed.
    if len(raw) != 66:
        return None, None
    val = int(raw, 16)
    scaled = val / MULTIPLIER_SCALE
    if not (0.0001 < scaled < 10000):
        return None, None
    return scaled, val
