"""Sign and send execute() as the agent.

THE KEY NEVER LEAVES THIS MODULE. It is read from the environment, used to
sign, and never returned, logged, printed or embedded in an error string. Every
error that leaves here goes through `_safe`, which refuses to emit anything
containing the key material — a private key that reaches a log is a private key
that is gone, and failure paths are where that happens.

It is also never passed as a command-line argument, so it cannot be read from
the process table of a shared runner.

Sending is opt-in twice over: VECTRA_EXECUTE=1 AND a key present. Absent either,
this module builds the transaction and refuses to send it, which is also how the
send path is tested without spending anything.
"""

import json
import os
import urllib.request

from eth_abi import encode as abi_encode
from eth_account import Account
from eth_utils import keccak

RPC = os.environ.get("VECTRA_RPC", "https://rpc.xlayer.tech")
CHAIN_ID = int(os.environ.get("VECTRA_CHAIN_ID", "196"))
KEY_ENV = "VECTRA_AGENT_KEY"

EXECUTE_SIG = "execute(uint256,address,address,uint256,uint256,bytes,address[])"
EXECUTE_SELECTOR = keccak(text=EXECUTE_SIG)[:4]


def _key():
    k = (os.environ.get(KEY_ENV) or "").strip()
    if not k:
        return None
    return k if k.startswith("0x") else "0x" + k


def _safe(msg):
    """Never let key material out, whatever a library decided to put in a string."""
    k = _key()
    text = str(msg)
    if k:
        for form in (k, k[2:], k.lower(), k[2:].lower()):
            if form and form in text:
                text = text.replace(form, "<redacted>")
    return text[:400]


def agent_address():
    """The address the key controls, or None. Printing this is safe."""
    k = _key()
    if not k:
        return None
    try:
        return Account.from_key(k).address
    except Exception:
        return None


def encode_execute(mandate_id, token_in, token_out, amount_in, min_out,
                   router_calldata, sweep):
    """ABI-encode the call. Hand-built so the encoding is visible here rather
    than depending on an ABI file staying in step with the contract."""
    if isinstance(router_calldata, str):
        router_calldata = bytes.fromhex(router_calldata[2:]
                                        if router_calldata.startswith("0x")
                                        else router_calldata)
    args = abi_encode(
        ["uint256", "address", "address", "uint256", "uint256", "bytes", "address[]"],
        [int(mandate_id), token_in, token_out, int(amount_in), int(min_out),
         router_calldata, list(sweep)],
    )
    return EXECUTE_SELECTOR + args


def _rpc(method, params):
    req = urllib.request.Request(
        RPC, json.dumps({"jsonrpc": "2.0", "id": 1,
                         "method": method, "params": params}).encode(),
        {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=40) as r:
        out = json.loads(r.read())
    if "error" in out:
        raise RuntimeError(f"{method}: {json.dumps(out['error'])[:300]}")
    return out["result"]


def send_execute(contract, mandate_id, token_in, token_out, amount_in, min_out,
                 router_calldata, sweep=(), dry_run=False):
    """Build, sign and send. Returns (result, error) and never raises.

    `dry_run` builds and signs nothing — it stops before sending so the whole
    path up to the wire can be exercised without spending anything.
    """
    key = _key()
    if not key:
        return None, f"{KEY_ENV} is not set; refusing to send"

    try:
        acct = Account.from_key(key)
        data = encode_execute(mandate_id, token_in, token_out, amount_in,
                              min_out, router_calldata, sweep)

        # Estimate first. A leg that cannot be estimated cannot be sent, and
        # finding that out here costs nothing while finding it out on chain
        # costs gas and records a failure that was never a real attempt.
        tx = {"from": acct.address, "to": contract, "data": "0x" + data.hex()}
        gas = int(_rpc("eth_estimateGas", [tx]), 16)
        gas_price = int(_rpc("eth_gasPrice", []), 16)
        nonce = int(_rpc("eth_getTransactionCount", [acct.address, "pending"]), 16)
        balance = int(_rpc("eth_getBalance", [acct.address, "latest"]), 16)

        cost = gas * gas_price
        if balance < cost:
            return None, (f"agent has {balance} wei, needs {cost} for gas")

        if dry_run:
            return {"dryRun": True, "gas": gas, "gasPrice": gas_price,
                    "nonce": nonce, "from": acct.address,
                    "calldataBytes": len(data)}, None

        signed = Account.sign_transaction({
            "to": contract, "data": "0x" + data.hex(),
            "gas": int(gas * 1.2), "gasPrice": int(gas_price * 1.2),
            "nonce": nonce, "chainId": CHAIN_ID, "value": 0,
        }, key)

        tx_hash = _rpc("eth_sendRawTransaction",
                       ["0x" + signed.raw_transaction.hex()])
        return {"txHash": tx_hash, "gas": gas, "from": acct.address}, None
    except Exception as e:
        return None, _safe(repr(e))


def wait_for_receipt(tx_hash, tries=40, delay=3):
    """Poll for the receipt. A send is not an execution until it is mined."""
    import time
    for _ in range(tries):
        try:
            r = _rpc("eth_getTransactionReceipt", [tx_hash])
        except Exception as e:
            return None, _safe(repr(e))
        if r:
            return {"status": int(r["status"], 16),
                    "gasUsed": int(r["gasUsed"], 16),
                    "blockNumber": int(r["blockNumber"], 16)}, None
        time.sleep(delay)
    return None, "receipt did not arrive in time"
