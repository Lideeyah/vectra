# Deployment runbook

Everything here is blocked on funds. Nothing else in Vectra is.

The ordering below is not arbitrary. **The convergence evidence cannot be
backfilled.** The distance series appends one row per agent cycle and starts
only once a real mandate exists for the agent to cycle against; every hour
between deployment and submission is an hour of evidence that either exists or
does not. So this runs at the *front* of a day, not the end of one.

---

## 0. Before anything is signed

**The deployer must still be at nonce 0.** The contract address is a CREATE
address predicted from `0x2F45E637920Cc7C7BE15130ab49224C989572AD8` at nonce 0,
and it is baked into `web/lib/config.ts`, the fork tests, and the caller-binding
payload. One unrelated transaction from that account moves the address.

```bash
cast nonce 0x2F45E637920Cc7C7BE15130ab49224C989572AD8 --rpc-url https://rpc.xlayer.tech
```

Must print `0`. If it does not, stop: the predicted address is wrong and every
recorded hash and payload built against it has to be regenerated.

---

## 1. Regenerate the bytecode hash and constructor args TOGETHER

These are a **matched pair**. The recorded hash in SPEC 5.2.4 describes a build
of specific sources with specific constructor arguments; regenerating one
without the other produces a pair that has never existed, and the mismatch will
not surface until explorer verification fails after the contract is immutable on
chain.

Do this as the *last* step before deploying, after the final contract change:

```bash
forge build && ./scripts/test.sh --fork
```

Then regenerate both and record them in SPEC 5.2.4 in the same edit.

---

## 2. Deploy

Deploy from the frozen deployer at nonce 0. Verify the deployed address equals
the predicted one before doing anything else with it.

---

## 3. Verify on OKLink

Needs an OKLink API key in hand first. Verification uses the **deployment
profile** — `evm_version = paris`, `optimizer_runs = 200`, `solc 0.8.24` — not
the fork profile. Building the fork profile produces different bytecode and
verification will fail with no useful message.

---

## 4. Point the interface at the deployed address

`NEXT_PUBLIC_VECTRA_ADDRESS` in the host's environment.

---

## 5. Confirm the host is not shipping fork data

**This is a command that fails, not a box to tick.** CI already refuses to build
with `NEXT_PUBLIC_ALLOW_FORK_HISTORY` set, but CI is not the host: a hosting
provider has its own environment panel, and a default that can be overridden in
one place nobody checks is not a default.

So the guard lives in `web/next.config.mjs` and runs inside the production build
itself — wherever that build happens, on whatever machine. Setting the flag
stops the deploy:

```
Error: NEXT_PUBLIC_ALLOW_FORK_HISTORY is set to true in a production build.
```

Verified in both directions: the build exits 1 with the flag set and 0 without,
and `next dev` is unaffected because it runs with `NODE_ENV=development`, which
is how fork legs are still viewed locally.

**Then confirm it on the deployed artifact**, because a passing build proves the
flag was unset at build time and nothing else. Open the deployed site with no
wallet connected. The legs section must read:

> No legs recorded yet. This list is built from the contract's `Executed`
> events; until one is emitted there is nothing to show, and nothing is shown.

If instead it shows a leg table with a "Fork run, not mainnet" banner, the
deployed build has fork data in it. Unset the variable on the host and redeploy.

Note that a local `npm run build` will also fail while `.env.local` sets the
flag. That is correct — a production build is a production build — so pass
`NEXT_PUBLIC_ALLOW_FORK_HISTORY=false` for local build checks.

---

## 6. Fund and create the live mandate

Two transactions: the USDC allowance, then the mandate. The allowance is where
the real risk is taken and the interface says so before it is signed.

Cap the first mandate at an amount that is acceptable to lose outright. The
total cap is the loss bound, not a budget: it is the most that can be lost if
the agent key were fully compromised and the router hostile.

---

## 7. Start the agent cycling, and let it run

This is when the convergence evidence starts existing. Confirm the first cycle
appended a row:

```bash
tail -3 data/agent/distance.csv
```

A row with `status=priced` and a number in `distance_bps` is a measured cycle.
`NA` means the cycle could not price every position and recorded no distance
rather than a partial one — expected occasionally, a problem if persistent.

---

## Exit, if it is needed

Pause stops the agent immediately and sells nothing. Revoke is permanent.

**Revoking the mandate does not revoke the USDC allowance.** They are two
permissions and only one of them is the mandate. Clear the allowance separately
— the interface shows it as its own object with the button next to it. See
SPEC 9.4.
