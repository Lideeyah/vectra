"""OKX DEX Aggregator (Onchain OS) read-only client. Quotes only — never signs or sends transactions."""

import base64
import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "https://web3.okx.com"
X_LAYER = "196"


KEYS = ("OKX_API_KEY", "OKX_SECRET_KEY", "OKX_PASSPHRASE", "OKX_PROJECT_ID")


def load_env(path=".env"):
    """Process environment wins (CI secrets); .env is the local fallback."""
    env = {k: os.environ[k] for k in KEYS if os.environ.get(k)}
    if len(env) < len(KEYS) and Path(path).exists():
        for line in Path(path).read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            if k in KEYS and not env.get(k):
                env[k] = v.strip().strip('"').strip("'")
    missing = [k for k in KEYS if not env.get(k)]
    if missing:
        raise SystemExit(f"Missing credentials: {', '.join(missing)}")
    return env


ENV = None


def request(path, params=None):
    """Signed GET. Returns (status, parsed_body_or_raw_text)."""
    global ENV
    if ENV is None:
        ENV = load_env()
    qs = "?" + urllib.parse.urlencode(params) if params else ""
    request_path = path + qs
    ts = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + ".000Z"
    sign = base64.b64encode(
        hmac.new(
            ENV["OKX_SECRET_KEY"].encode(),
            (ts + "GET" + request_path).encode(),
            hashlib.sha256,
        ).digest()
    ).decode()
    req = urllib.request.Request(
        BASE + request_path,
        headers={
            "OK-ACCESS-KEY": ENV["OKX_API_KEY"],
            "OK-ACCESS-SIGN": sign,
            "OK-ACCESS-TIMESTAMP": ts,
            "OK-ACCESS-PASSPHRASE": ENV["OKX_PASSPHRASE"],
            "OK-ACCESS-PROJECT": ENV["OKX_PROJECT_ID"],
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw, status = r.read().decode(), r.status
    except urllib.error.HTTPError as e:
        raw, status = e.read().decode(), e.code
    except Exception as e:
        return 0, {"transport_error": repr(e)}
    try:
        return status, json.loads(raw)
    except json.JSONDecodeError:
        return status, raw


def all_tokens(chain=X_LAYER):
    """Token list for a chain. Tries v5 and v6 param spellings."""
    attempts = [
        ("/api/v5/dex/aggregator/all-tokens", {"chainId": chain}),
        ("/api/v6/dex/aggregator/all-tokens", {"chainIndex": chain}),
    ]
    out = []
    for path, params in attempts:
        status, body = request(path, params)
        out.append((path, status, body))
        if isinstance(body, dict) and body.get("code") == "0" and body.get("data"):
            return body["data"], out
    return None, out


def quote(from_addr, to_addr, amount_base_units, chain=X_LAYER, slippage="0.01"):
    """Single aggregator quote. amount is in the from-token's smallest units."""
    params = {
        "chainId": chain,
        "amount": str(amount_base_units),
        "fromTokenAddress": from_addr,
        "toTokenAddress": to_addr,
        "slippage": slippage,
    }
    status, body = request("/api/v5/dex/aggregator/quote", params)
    if isinstance(body, dict) and body.get("code") not in ("0", 0):
        p6 = dict(params)
        p6["chainIndex"] = p6.pop("chainId")
        s6, b6 = request("/api/v6/dex/aggregator/quote", p6)
        if isinstance(b6, dict) and b6.get("code") in ("0", 0):
            return s6, b6
    return status, body


def routes_of(data):
    """Flatten the DEX/liquidity sources used by a quote into 'Name pct%' strings."""
    sources = []
    for router in data.get("dexRouterList") or []:
        for sub in router.get("subRouterList") or []:
            for proto in sub.get("dexProtocol") or []:
                sources.append(f"{proto.get('dexName')} {proto.get('percent')}%")
    if not sources:
        for proto in data.get("quoteCompareList") or []:
            sources.append(proto.get("dexName", "?"))
    return sources
