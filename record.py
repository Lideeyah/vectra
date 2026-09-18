"""Vectra price recorder. One CSV row per asset per cycle.

Read-only: requests quotes and reads chain state. It never builds, signs or
sends a transaction.

Missing data is never represented by null, empty string or zero. A failed quote
writes a row with status=failed and the literal sentinel NA in every numeric
field, so a gap in the series is visible rather than inferred.

Dedupe is by (bucket, symbol) where bucket is the reading floored to five
minutes. A late or overlapping run therefore cannot write a duplicate reading.
"""

import csv
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import okx_dex
import xlayer

NA = "NA"
CADENCE_MIN = 5
NOTIONAL_USD = 5.0
RUN_MINUTES = int(os.environ.get("VECTRA_RUN_MINUTES", "330"))
THROTTLE_S = 1.1

CONSTITUENTS = Path("data/constituents.json")
CSV_PATH = Path("data/prices.csv")

COLUMNS = [
    "ts_utc", "bucket", "cycle", "status", "symbol", "address", "decimals",
    "usd_in", "amount_out", "price_usd", "price_impact_pct",
    "multiplier", "multiplier_raw", "routes", "reason",
]


def now():
    return datetime.now(timezone.utc)


def bucket_of(dt):
    return dt.replace(second=0, microsecond=0,
                      minute=(dt.minute // CADENCE_MIN) * CADENCE_MIN
                      ).isoformat(timespec="minutes")


def existing_keys(window_hours=6):
    """(bucket, symbol) pairs already recorded recently, to suppress duplicates."""
    if not CSV_PATH.exists():
        return set()
    cutoff = (now() - timedelta(hours=window_hours)).isoformat(timespec="minutes")
    keys = set()
    with open(CSV_PATH, newline="") as f:
        for row in csv.DictReader(f):
            if (row.get("bucket") or "") >= cutoff:
                keys.add((row["bucket"], row["symbol"]))
    return keys


def append(rows):
    CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    new_file = not CSV_PATH.exists()
    with open(CSV_PATH, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        if new_file:
            w.writeheader()
        for r in rows:
            w.writerow(r)


def read_constituents():
    import json
    if not CONSTITUENTS.exists():
        return None
    return json.loads(CONSTITUENTS.read_text())


def quote_row(cyc, bucket, usdc, asset):
    """One asset. Any failure is contained to this row and never raises."""
    sym = asset["symbol"]
    addr = asset["address"]
    dec_out = int(asset["decimals"])
    dec_in = int(usdc["decimals"])
    amount = int(round(NOTIONAL_USD * 10 ** dec_in))

    row = {c: NA for c in COLUMNS}
    row.update({
        "ts_utc": now().isoformat(timespec="seconds"),
        "bucket": bucket,
        "cycle": cyc,
        "symbol": sym,
        "address": addr,
        "decimals": dec_out,
        "usd_in": NOTIONAL_USD,
        "reason": "",
    })

    # Multiplier is independent of the quote: record it even if pricing fails.
    try:
        mult, mult_raw = xlayer.multiplier(addr)
    except Exception:
        mult, mult_raw = None, None
    if mult is not None:
        row["multiplier"] = f"{mult:.18f}".rstrip("0")
        row["multiplier_raw"] = str(mult_raw)

    try:
        status, body = okx_dex.quote(usdc["address"], addr, amount)
    except Exception as e:
        row.update({"status": "failed", "reason": f"transport:{e!r}"[:200]})
        return row

    if not isinstance(body, dict) or body.get("code") not in ("0", 0) or not body.get("data"):
        detail = body.get("msg") if isinstance(body, dict) else str(body)[:160]
        code = body.get("code") if isinstance(body, dict) else "?"
        row.update({"status": "failed",
                    "reason": f"http={status} code={code} msg={detail}"[:200]})
        return row

    d = body["data"][0] if isinstance(body["data"], list) else body["data"]
    try:
        out_units = int(d.get("toTokenAmount"))
    except (TypeError, ValueError):
        row.update({"status": "failed", "reason": "toTokenAmount unparseable"})
        return row

    if out_units <= 0:
        row.update({"status": "failed", "reason": "zero output — no route at this size"})
        return row

    amt_out = out_units / (10 ** dec_out)
    row.update({
        "status": "ok",
        "amount_out": f"{amt_out:.18f}".rstrip("0"),
        "price_usd": f"{NOTIONAL_USD / amt_out:.10f}",
        "price_impact_pct": d.get("priceImpactPercentage") or NA,
        "routes": "|".join(okx_dex.routes_of(d)) or NA,
    })
    return row


def record_bucket(cyc, usdc, assets):
    """One bucket. Returns (written, ok_count)."""
    bucket = bucket_of(now())
    done = existing_keys()

    rows, skipped = [], 0
    for a in assets:
        if (bucket, a["symbol"]) in done:
            skipped += 1
            continue
        rows.append(quote_row(cyc, bucket, usdc, a))
        time.sleep(THROTTLE_S)

    if not rows:
        print(f"{bucket}: already complete ({skipped} assets)")
        return 0, 0

    append(rows)
    ok = sum(1 for r in rows if r["status"] == "ok")
    mult_ok = sum(1 for r in rows if r["multiplier"] != NA)
    print(f"{bucket}: {ok}/{len(rows)} ok, {mult_ok} multipliers, {skipped} deduped")
    for r in rows:
        if r["status"] != "ok":
            print(f"    {r['symbol']:<10} FAILED {r['reason'][:80]}")
    return len(rows), ok


def main():
    """Record continuously for RUN_MINUTES rather than once per invocation.

    GitHub's five minute cron is unreliable — observed firing roughly every four
    hours, giving 2.7% coverage of the intended series. Since the series cannot
    be backfilled, each job stays alive and records its own buckets on a real
    clock instead of depending on the scheduler to wake it.
    """
    cyc = os.environ.get("GITHUB_RUN_ID") or str(int(time.time()))
    cons = read_constituents()
    if cons is None:
        print("data/constituents.json missing — run discover.py first to fix the set.",
              file=sys.stderr)
        return 1

    usdc = cons["usdc"]
    assets = cons["constituents"]
    deadline = time.time() + RUN_MINUTES * 60
    total_rows = total_ok = cycles = 0

    print(f"recording {len(assets)} assets for {RUN_MINUTES} min "
          f"on a {CADENCE_MIN} min cadence")

    while True:
        wrote, ok = record_bucket(cyc, usdc, assets)
        total_rows += wrote
        total_ok += ok
        cycles += 1

        # Sleep to the start of the next bucket, not a fixed interval, so
        # readings stay aligned to the cadence even when a cycle runs long.
        nxt = (now() + timedelta(minutes=CADENCE_MIN)).replace(second=0, microsecond=0)
        nxt = nxt.replace(minute=(nxt.minute // CADENCE_MIN) * CADENCE_MIN)
        wait = (nxt - now()).total_seconds()
        if time.time() + max(wait, 0) > deadline:
            break
        if wait > 0:
            time.sleep(wait)

    print(f"\n{cycles} cycles, {total_rows} rows, {total_ok} quotes recorded")
    return 0 if total_ok > 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
