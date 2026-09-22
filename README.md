# Vectra

Vectra is a self maintaining basket of tokenised equities on X Layer: an owner signs one mandate with hard limits, and an agent trades the basket back toward its target through the OKX DEX aggregator, one leg at a time, without asking for approval per trade.

## What is live right now

| | |
|---|---|
| Contract | [`0x08Ed8562e2fD44C82EBA0CDfbC6F5Fdca3Cf19a0`](https://www.oklink.com/x-layer/address/0x08Ed8562e2fD44C82EBA0CDfbC6F5Fdca3Cf19a0) (Contracts tab, source verified) |
| Chain | X Layer, chain id 196 |
| App | https://vectra-market.vercel.app |
| Demo | [youtu.be/QD2a7lPcwrk](https://youtu.be/QD2a7lPcwrk), 3:00 |

Read from the contract at **2026-09-22T11:51Z** by calling `mandate(1)`, not copied from a log:

| | |
|---|---|
| Legs executed | 23 |
| Mandate version | 4, after four recorded target changes |
| Cap | 4.000000 USDC |
| Spent | 3.837638 USDC, leaving 0.162362 |
| Tolerance | 500 bps |
| Max leg | 1.000000 USDC |
| Expiry | 2026-10-05T10:23:03Z |
| Owner | `0x2F45E637920Cc7C7BE15130ab49224C989572AD8` |
| Agent | `0x083dCD15548a5A6504f774c7F16d28a454bFD656` |

Reproduce that row yourself:

```bash
cast call 0x08Ed8562e2fD44C82EBA0CDfbC6F5Fdca3Cf19a0 "mandate(uint256)" 1 --rpc-url https://rpc.xlayer.tech
```

Fields are in the order given by `Mandate` in [contracts/VectraMandate.sol](contracts/VectraMandate.sol): owner, agent, expiry, `maxLegBpsOfTarget`, version, paused, revoked, `driftBps`, `maxLegUsdc`, `totalCapUsdc`, `spentUsdc`.

## Check it yourself

Everything below runs from a fresh clone. The only external dependency is [Foundry](https://book.getfoundry.sh/getting-started/installation) for `cast` and `forge`, plus Python 3. The RPC is the public X Layer endpoint `https://rpc.xlayer.tech` and needs no key or account.

```bash
git clone --recursive https://github.com/Lideeyah/vectra && cd vectra
forge build
```

`--recursive` is not optional. OpenZeppelin and forge-std are git submodules, so
a plain clone leaves `lib/` empty and `forge build` fails. If you already cloned
without it, run `git submodule update --init --recursive`.

### 1. The deployed bytecode is the source in this repo

```bash
python3 tools/verify_bytecode.py
```

A raw byte comparison fails on this contract, and that is expected rather than a problem: the router, spender and USDC addresses are `immutable`, so the compiler writes them into the deployed code at construction. The script masks exactly the slots the build artifact records in `immutableReferences`, compares everything else, and then prints what it found inside those slots so the constructor arguments are checked rather than skipped. It exits non zero if either half fails.

Expected output: `code outside immutables: EXACT MATCH`, and three immutable values resolving to router, spender and USDC.

The same claim is checkable without this repo at all, on the contract's [OKLink Contracts tab](https://www.oklink.com/x-layer/address/0x08Ed8562e2fD44C82EBA0CDfbC6F5Fdca3Cf19a0), which reads "Contract source code verified" against solc `v0.8.24+commit.e11b9ed9` with optimizer on at 200 runs.

### 2. The cap bounds what a compromised agent can take

```bash
forge test --match-contract AdversarialTest --match-test test_BlastRadius -vv
```

This runs [test/Adversarial.t.sol](test/Adversarial.t.sol) against a `PredatoryRouter` that simply drains whatever it is given. The test hands the agent key to an attacker, sets `minOut` to zero, and loops calling `execute` in maximum sized legs until the contract refuses. It then asserts the owner's realised loss is at most the mandate cap and strictly less than their whole balance, and prints both numbers so you can read the actual figure rather than trust the assertion.

### 3. The legs listed are real

One leg, checked directly, in a second:

```bash
cast tx 0x7f541f629ddefe8fc12849f6933494758e403b91fa97631da61544b3c4b3608f --rpc-url https://rpc.xlayer.tech
```

All of them, rebuilt from the contract's own `Executed` events:

```bash
python3 tools/export_mainnet_history.py
```

That walks from the deployment block in 95 block chunks and takes roughly twenty minutes, because X Layer **refuses** an `eth_getLogs` range wider than 100 blocks rather than merely being slow. It overwrites `data/history.json`, which is the file the app renders, so a full scan is also a diff against what is being shown.

## How it works

**The mandate.** [`createMandate`](contracts/VectraMandate.sol) records a basket, target share counts, and four limits that the contract enforces on every leg:

- `driftBps`, the tolerance band. Checked **per position**, not against summed distance.
- `maxLegUsdc`, the most USDC one leg may spend.
- `totalCapUsdc`, cumulative USDC spend for the life of the mandate. A sell does **not** refund headroom, so `$4` spent is exhausted whatever is later sold. The reasoning is in SPEC 5.2.1.
- `maxLegBpsOfTarget`, the most of a token's target share count one leg may move. The USDC leg cap cannot bound a sell, since it is denominated in dollars and the contract holds no prices, so the rate bound is expressed in shares instead.

Targets are held in **shares**, not weights, because the xStocks rebase: `balanceOf` changes when the issuer moves the multiplier while `sharesOf` does not. The contract also refuses any leg that would carry a position past its target (`Overshoot`) or in the wrong direction (`WrongDirection`).

The owner keeps control throughout: pause, resume, revoke, and `amendTargets`, which emits both the old and new targets and increments the version. Every leg emits the version in force when it ran, so a gap that closed because the target moved cannot be mistaken for one closed by trading.

**The loop.** [agent.py](agent.py) prices each position through the OKX aggregator, measures each holding's gap to target in shares, and selects the single leg that most reduces total distance. One trade per cycle is a contract level constraint, not a pacing choice, and the agent uses L1 distance so the best single leg is the one closing the largest single gap.

**The log.** Every cycle publishes what it decided to [data/agent/latest.json](data/agent/latest.json), including the positions it could price, the leg it chose or why it chose none, and its refusals. The most recent cycle recorded no leg with the reason `largest drift 476bps is within tolerance 500bps`. Refusals are carried in the same file and are visible in the app, including standing ones the product has not solved.

The per cycle distance series is appended to [data/agent/distance.csv](data/agent/distance.csv), one row per cycle, never rewritten. A cycle that could not price every position records `NA` and breaks the chart line rather than being interpolated across.

## The bound

`test_BlastRadius_CompromisedAgent_HostileRouter_UsdcLoss` assumes the worst realistic case: the agent key is stolen and the router is actively malicious. It then measures, rather than argues, what the owner loses. The contract's accounting stops the attacker at the cap, and the test asserts that.

**What this proves and what it does not.** The cap bounds loss from a **compromised agent key**. It does not bound loss from a bug in the contract's own accounting, because the same code enforces the cap and computes `spentUsdc`. Nothing inside a contract can bound a mistake in the arithmetic that does the bounding. The contract is immutable and has no admin key, so anything missed in review is missed permanently. That is the honest shape of the guarantee.

Loss is also bounded in practice by how little the key holds: the agent address funds its own gas and can commit at most the remaining cap.

## Limits and open items

- **Runs are started by hand.** GitHub's scheduled triggers proved unreliable here, so the keeper is started manually. Of the 23 legs on chain, **23 came from `workflow_dispatch` runs and none from `schedule`**, cross referenced from the public Actions API against each leg's block timestamp. What is true is narrower than "it runs on a schedule": no trade required a per trade approval, and the agent chose the asset, direction and size and signed it on its own.
- **The keeper's commits lag its trades.** Legs land on chain before the cycle log and distance row are committed, so the app can show a cycle log older than the chain state above it.
- **No pause around multiplier activation.** The issuer asks integrations to halt briefly either side of a rebase activation. Those timestamps are not published anywhere machine readable, so legs run through those windows instead of waiting them out. This is recorded as a standing refusal in every cycle log rather than hidden, and is SPEC 14.
- **`maxLegBpsOfTarget` has no getter.** It is set at creation and enforced on every leg, but cannot be read back from the contract, so the interface shows it from configuration and says on screen that it is not a chain read.
- **The distance series cannot be backfilled.** It begins when recording began, so it is shorter than the mandate's life and always will be.
- **A second copy of the app is published to GitHub Pages** by [.github/workflows/pages.yml](.github/workflows/pages.yml) and is live at `lideeyah.github.io/vectra`. The canonical host is the Vercel URL above. Deleting the workflow would freeze the stale copy rather than remove it; turning Pages off in the repository settings is the actual fix, and it has not been done.
- **OKLink displays `evmVersion` as `default`** on the verified source, although the submitted standard JSON input pinned `paris`. The bytecode matched regardless, which is what verification checks.

## Build and run

```bash
forge build
./scripts/test.sh              # 61 tests, unit and adversarial
./scripts/test.sh --fork       # the above plus 15 against forked X Layer

cd web && npm install && npm run dev   # http://localhost:3000
```

The fork suite needs only the public RPC, no key and no account. It skips
`test/fork/CallerBinding.t.sol` and says so, because that test replays a real
aggregator payload from `VECTRA_PAYLOAD`, which `fetch_payload.py` produces and
which needs OKX credentials. A missing credential is not a broken contract.

The interface needs no configuration to run. Every value falls back to the live
deployment, so a fresh clone points at the real contract and the committed data
without an env file.

The fork suite runs under its own profile at `evm_version = cancun` because the forked chain runs Uniswap V4, which needs transient storage. The deployment profile stays pinned at `paris` for reproducibility. `./scripts/test.sh --prove-split` asserts the two cannot be run under each other by accident.

The agent needs OKX DEX API credentials in `.env` (`OKX_API_KEY`, `OKX_SECRET_KEY`, `OKX_PASSPHRASE`, `OKX_PROJECT_ID`) from [OKX's developer portal](https://web3.okx.com/build/dev-portal), and `VECTRA_AGENT_KEY` to sign. The key is read from the environment only, never passed as an argument and never logged; see [send.py](send.py).

## Repo layout

```
contracts/VectraMandate.sol   the mandate and its limits
agent.py                      pricing, distance, leg selection
send.py                       signing, with key redaction
test/                         unit, rebase surface, adversarial
test/fork/                    real router against forked X Layer
tools/verify_bytecode.py      deployed code vs this repo
tools/export_mainnet_history.py  rebuild history from Executed events
web/                          the interface, static export
data/                         committed recorder and agent output
SPEC.md  DESIGN.md  DEPLOY.md decisions, design system, deployment record
```

## Licence

MIT. See the SPDX headers in `contracts/` and [LICENSE](LICENSE).
