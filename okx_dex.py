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

# Cloudflare fronts these hosts and rejects default library user agents with
# error 1010 before the request reaches OKX. Identify as a normal client.
USER_AGENT = os.environ.get(
    "OKX_USER_AGENT",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
)

# web3.okx.com is the Cloudflare-fronted site; www.okx.com has historically
# served the same DEX routes. Try both before declaring a path unreachable.
HOSTS = ["https://web3.okx.com", "https://www.okx.com"]
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
    headers = {
        "OK-ACCESS-KEY": ENV["OKX_API_KEY"],
        "OK-ACCESS-SIGN": sign,
        "OK-ACCESS-TIMESTAMP": ts,
        "OK-ACCESS-PASSPHRASE": ENV["OKX_PASSPHRASE"],
        "OK-ACCESS-PROJECT": ENV["OKX_PROJECT_ID"],
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
        "User-Agent": USER_AGENT,
    }

    last = (0, {"transport_error": "no hosts attempted"})
    for host in HOSTS:
        req = urllib.request.Request(host + request_path, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                raw, status = r.read().decode(), r.status
        except urllib.error.HTTPError as e:
            raw, status = e.read().decode(), e.code
        except Exception as e:
            last = (0, {"transport_error": repr(e), "host": host})
            continue
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            body = {"non_json_body": raw[:400], "host": host}
        if status == 200 and isinstance(body, dict):
            return status, body
        last = (status, body if isinstance(body, dict) else {"body": body, "host": host})
    return last


# v5 returns code 50050 ("V5 API is being deprecated") for most calls on this
# chain, so v6 is primary. v5 is kept only as a last resort.
VERSIONS = [
    ("/api/v6/dex/aggregator/{}", "chainIndex"),
    ("/api/v5/dex/aggregator/{}", "chainId"),
]


def _ok(body):
    return isinstance(body, dict) and body.get("code") in ("0", 0) and body.get("data")


def endpoint(name, params, chain=X_LAYER):
    """Call an aggregator endpoint across API versions.

    On total failure the returned body carries EVERY attempt. An earlier
    version's error must never stand in for a later one's — that masking is
    what made a deprecation notice look like 594 illiquid tokens.
    """
    attempts = []
    for template, chain_key in VERSIONS:
        path = template.format(name)
        p = dict(params)
        p[chain_key] = chain
        status, body = request(path, p)
        attempts.append((path, status, body))
        if _ok(body):
            return status, body, attempts
    # Report the PRIMARY version's failure, not the last one tried. v5 answers
    # almost everything with its deprecation notice, and letting that stand in
    # for v6's real error is the same masking bug twice over.
    primary_status, primary_body = attempts[0][1], attempts[0][2]
    merged = dict(primary_body) if isinstance(primary_body, dict) else {"body": primary_body}
    merged["attempts"] = [
        {"path": p, "status": s,
         "code": b.get("code") if isinstance(b, dict) else None,
         "msg": str(
             (b.get("msg") or b.get("transport_error") or b.get("non_json_body") or b)
             if isinstance(b, dict) else b)[:200]}
        for p, s, b in attempts
    ]
    return primary_status, merged, attempts


def all_tokens(chain=X_LAYER):
    status, body, attempts = endpoint("all-tokens", {}, chain)
    if _ok(body):
        return body["data"], attempts
    return None, attempts


def quote(from_addr, to_addr, amount_base_units, chain=X_LAYER, slippage="0.01"):
    """Single aggregator quote. amount is in the from-token's smallest units."""
    status, body, _ = endpoint("quote", {
        "amount": str(amount_base_units),
        "fromTokenAddress": from_addr,
        "toTokenAddress": to_addr,
        "slippage": slippage,
    }, chain)
    return status, body


def routes_of(data):
    """Flatten the liquidity sources a quote used.

    Shape-agnostic on purpose: v5 and v6 nest this differently, and reading v5
    field names against a v6 body silently produced an empty route list. Walk
    the structure and collect anything that names a DEX, wherever it sits.
    """
    sources, seen = [], set()

    def walk(node):
        if isinstance(node, dict):
            name = node.get("dexName") or node.get("dexProtocolName") or node.get("name")
            if name and isinstance(name, str):
                pct = node.get("percent") or node.get("routerPercent")
                label = f"{name} {pct}%" if pct else name
                if label not in seen:
                    seen.add(label)
                    sources.append(label)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(data)
    return sources
