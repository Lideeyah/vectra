# Vectra — Architecture and Product Specification

X Layer, chain ID 196. OKX Dev Day 2026, Build a Market track. Solo build, eight days.

This document settles what is built before any code exists. It covers the chain architecture, the agent, the frontend, every user flow, every state, and the invariants that must hold. It does not cover visual design, which is decided separately.

---

## 1. WHAT VECTRA IS

A basket of tokenised equities that maintains itself, at any size, including five dollars.

The user chooses a set of xStocks and target weights. They sign an on-chain mandate that defines the basket, the drift tolerance, the maximum size of any single trade, the total amount that may ever be spent, and an expiry. An agent holds no keys to their funds and cannot exceed that mandate. It watches the position, and when actual weights drift beyond tolerance it buys and sells to bring them back.

The tokens live in the user's own wallet throughout. The contract never holds a balance between transactions. The mandate can be paused or revoked at any moment.

---

## 2. THE USER AND THE JOB

Someone outside the United States, in one of the 110-plus eligible countries, holding somewhere between five and a few hundred dollars, who wants diversified equity exposure rather than a single stock.

Every existing product refuses this person. Robo-advisors carry minimums between five hundred and five thousand dollars. Brokerages will not actively manage a fifty dollar account. The reason is always the same: transaction costs are fixed, so at small size the cost of managing the portfolio exceeds the benefit of managing it.

On X Layer that constraint appears not to exist. Observed in the OKX DEX aggregator interface at web3.okx.com/dex-swap with the chain set to X Layer: one dollar of USDC into NVDAx quoted 0.00458549352 NVDAx at $0.99, marked −0.35%, network fee shown as Free, routed through the OKX DEX Aggregator across four hops. Twenty five cents quoted 0.001146371251 NVDAx at $0.24, also −0.35%, also Free, on the same route. The rate line read 1 USDC ≈ 0.004585 NVDAx at both sizes. The service fee is 0.25%, so slippage accounts for the remaining tenth of a percent.

**Status of this reading.** It was taken from the aggregator's own interface, not through the API, and it is a single observation at one moment. It is reproduced through the API by the price recorder, and the recorded series is the evidence of record. Until that reproduction is in hand, treat the figure as a well-founded observation rather than a verified constant.

Cost appears to be purely proportional. A twenty five cent leg costs the same percentage as a twenty five thousand dollar one. That is the fact the entire product rests on, and if it fails to reproduce, sections 2A and 3 need revisiting before anything else.

---

## 2A. THE CLAIM THAT DIFFERENTIATES THIS

Access at small size is the obvious consequence of free execution and anyone can reach it. The sharper consequence is accuracy.

Every index product in existence tolerates drift, and the tolerance exists because rebalancing is billable. Vanguard rebalances on a schedule. Robo-advisors use drift bands around five percent. Exchange-traded funds publish tracking error as a headline figure precisely because they cannot track perfectly. None of those numbers were chosen as optimal. They were chosen because you wait until the drift is worth more than the cost of correcting it.

The argument is therefore about what sets the band, not about comparing two percentages.

A rebalance costs a fixed component plus a proportional component. The fixed component — network fees, ticket charges, the minimum viable trade a broker will accept — does not shrink with account size, so at small size it dominates. A manager choosing a drift band is choosing the point at which correcting the drift is worth paying that fixed cost. The smaller the account, the wider the band has to be, which is why a fifty dollar account is refused outright rather than managed badly.

On X Layer the fixed component is reported as zero at any size, and the proportional component is the spread: a 0.25% service fee plus roughly a tenth of a percent of slippage. If that holds, the band is no longer set by account size at all. It is set only by the spread, which is identical for a twenty five cent leg and a twenty five thousand dollar one.

So the claim is not that a twenty dollar portfolio is now affordable, and it is not that 0.35% is smaller than five percent, which would be comparing a cost to a tolerance. It is that **the constraint that forces every other product to pick a drift band — a fixed cost per rebalance — does not apply here, so a basket can be held to its target far more tightly, and equally tightly at any account size.**

How much more tightly is a measurement, not an assertion. Compute the tracking error of a continuously converging basket against the same basket rebalanced monthly and quarterly, from real recorded prices, and publish the numbers. Evidence computed from real data is the difference between an argument a judge can wave away and one they cannot. The price recorder exists to produce that series and is the reason it ships before anything else.

Two things follow from this.

**Baskets are indices, not arbitrary picks.** Tracking error is only meaningful against something being tracked, so the product ships with defined index baskets and the user chooses among them or composes one with stated weights that then become the target of record.

**Rebasing becomes a feature rather than a hazard.** Balances change with no transfer, which means every change can be attributed: this position grew because the price moved, that one grew because a dividend was reinvested. No tokenised equity product performs that decomposition today, and it falls directly out of the chain's own mechanism.

---

## 3. THE CORE TECHNICAL IDEA

Each swap is independent. A ten-position basket is ten separate transactions, any of which can fail on its own. There is no way to make ten swaps atomic, and a partially built basket is the obvious failure mode of any naive implementation.

The answer is not to fight for atomicity. It is to make the system **convergent**.

The contract stores a target state, meaning the basket and its weights. It does not store a plan. On every cycle the agent reads the current actual holdings, compares them to target, and executes the single leg that most reduces the distance between them. If that leg fails, nothing is corrupted, because the system never committed to a sequence. The next cycle recomputes from whatever is actually true and takes the next best step.

Any interruption leaves a valid intermediate state: some cash, some positions, a known distance from target. Nothing is ever half-committed, because nothing is ever committed as a batch.

This works only because execution is free. On a chain with real gas costs, converging over twenty cycles instead of one batch would be prohibitively expensive, which is why every existing system batches and then has to handle partial batches. Free execution turns the hard problem into a non-problem.

That connection, from free execution to convergence rather than atomicity, is the technical contribution of this build and it belongs at the centre of the submission.

---

## 4. RUNTIME TOPOLOGY

Four pieces, no backend server.

**A Solidity contract on X Layer** holding mandates and enforcing their limits. Deployed once, not upgradeable, no admin key.

**An agent** running on GitHub Actions cron, in the same pattern as previous builds. It holds one EOA keypair funded with a small amount of OKB for gas, reads chain state, requests quotes from the OKX DEX aggregator, and calls the contract. It has no authority beyond calling `execute` on mandates that name it.

**The repository as the action log.** Every cycle appends what the agent did and what it declined to do, committed with a timestamp. This is public, auditable, and costs nothing.

**A Next.js frontend on Vercel**, reading chain state directly through RPC, reading the action log from the repository, and proxying quote requests through a single serverless route so the OKX API key never reaches the browser.

---

## 5. ON-CHAIN ARCHITECTURE

### 5.1 The principle that bounds every bug

**The contract never holds user funds between transactions.** Its token balance is zero at the end of every call, asserted as an invariant.

The user grants an ERC-20 allowance to the contract for each token in the basket, capped at the mandate's total spend limit. The contract pulls exactly what a leg requires, swaps it through the aggregator router, and sends the output directly to the user's address in the same transaction.

If the contract is completely broken, the worst case is bounded by the allowance one user granted. For the demo that is a few dollars. This single design choice is worth more than every other safety measure combined.

### 5.2 Contract surface

`createMandate(address[] tokens, uint16[] weightsBps, uint16 driftBps, uint256 maxLegUsdc, uint256 totalCapUsdc, uint64 expiry, address agent)`

Stores the mandate against `msg.sender`. Weights must sum to 10000. Expiry must be in the future and within a maximum horizon. One active mandate per address in this version.

`execute(uint256 mandateId, address tokenIn, address tokenOut, uint256 amountIn, uint256 minOut, bytes routerCalldata)`

**What the contract can and cannot check.** Distance from target is defined in weight space, and weights require prices. This design has no oracle and does not want one, so the contract cannot compute portfolio distance and cannot prove that a leg is the optimal next step. Pretending otherwise would be claiming a check the code does not perform.

The contract therefore bounds the **size and direction** of trades, and leaves the choice of leg to the agent. It checks, in order:

- the mandate exists, is active, is not paused, is not expired
- the caller is the named agent
- `tokenIn` and `tokenOut` are both either USDC or members of the basket, and are not the same token
- when spending USDC, `amountIn` is at or below `maxLegUsdc`, and cumulative USDC spend after this leg is at or below `totalCapUsdc`
- **direction**: USDC may only be spent to buy a token whose current holding is below its target share of the basket, measured in the token's own units against the last recorded target, and a basket token may only be sold when its holding is above target

The direction rule is what survives the absence of prices. It does not prove the leg is optimal, and a compromised agent retains freedom to choose a suboptimal but still corrective leg. What it forecloses is the unbounded case: the agent cannot churn the position back and forth, cannot buy what is already at or above target, and cannot spend beyond the cap. That is a weaker guarantee than "every action reduces distance from target", and the difference is stated here rather than glossed.

**The division of labour.** The contract bounds direction and size. The agent optimises. The agent has prices and does the weight-space work; the contract has no prices and does not pretend to. Weight drift is the agent's problem, not the contract's, and that separation is clean rather than a compromise.

**Targets are share quantities, and this is a feature.** Targets are expressed in `sharesOf`, not `balanceOf`. The obvious reason is that the direction rule must not be fooled by a rebase. The better reason is durability: a target expressed in shares **survives a dividend or a split without amendment**, while a target expressed in balance terms silently becomes wrong the moment a CRWDx-style event fires. CRWDx already sits at a multiplier of 4.0 — a balance target set before that event would now be wrong by 300%, with no transaction having occurred to signal it.

So the coarser guarantee is also the more durable one. That is worth stating as a design property, not apologising for.

The honest limitation remains: a share quantity is a proxy for the value weights the product cares about, and it drifts from them as prices move. Re-targeting is an owner action, never an agent one.

**Every leg has USDC on one side.** Token-to-token legs are rejected. Beyond removing an unbounded-churn surface, this means cap accounting is always denominated in the unit the cap is written in. No conversion, no oracle, no ambiguity about what "spent" means.

Caps are denominated in USDC throughout, never in basket-token units. USDC does not rebase; xStocks do. A cap expressed in a rebasing token would silently change meaning when a multiplier activates.

Then it pulls `amountIn`, calls the router with `routerCalldata`, requires the received amount to be at least `minOut`, transfers the output to the mandate owner, and asserts the contract holds zero of both tokens.

`pause(uint256 mandateId)` and `resume(uint256 mandateId)`, owner only.

`revoke(uint256 mandateId)`, owner only, permanent. Does not move funds, since the contract holds none. The user separately revokes their allowances, and the interface prompts them to.

View functions for mandate state, cumulative spend, and holdings relative to target in token units.

### 5.3 What is deliberately absent

No upgradeability, no proxy, no admin role, no pause-everything switch, no fee mechanism, no loops over unbounded arrays, no delegatecall, no receiving ETH, and no price oracle. Basket size is capped at ten tokens.

Everything that can live in the agent lives in the agent. The contract only holds the rules that must not be breakable.

### 5.4 Dependencies

OpenZeppelin for `SafeERC20`, `ReentrancyGuard` and `Ownable` where needed. Nothing in this class is hand-rolled.

The router address for the OKX DEX aggregator is set at deployment and immutable. Only that address may be called with `routerCalldata`.

---

## 6. OFF-CHAIN ARCHITECTURE

### 6.1 The cycle

Every five minutes the agent, for each active mandate:

Reads the mandate from chain. Skips if paused, expired, revoked, or if cumulative spend has reached the cap.

Reads the owner's actual balances of USDC and every basket token.

Prices the position using quotes from the OKX DEX aggregator, not from a price feed, so the valuation reflects what could actually be executed.

Computes each position's current weight and its distance from target. **This computation is the agent's responsibility alone; the contract does not and cannot verify it.**

If the largest drift is within tolerance, records "within tolerance, no action" and exits. This is the common case and it must be cheap and visible.

If drift exceeds tolerance, selects the single leg that most reduces total distance, sized at or below `maxLegUsdc`.

Requests a quote for that leg, sets `minOut` from the quote with the user's slippage tolerance applied, and calls `execute`.

Records the outcome, including failures and refusals, and commits it.

### 6.2 What the agent refuses to do

It does not fire if a quote cannot be obtained, if the quote's implied price deviates beyond a sanity band from the previous cycle, if the allowance is insufficient, if the owner's balance is lower than the leg requires, if chain state cannot be read, or if the router returns a route it does not recognise.

Every refusal is recorded with its reason. The log of what the agent declined to do is as much a product surface as the log of what it did.

### 6.3 Keeper funding

The agent pays gas in OKB. Gas on X Layer is near zero but not literally zero for a plain EOA, so the keeper holds a small balance and the interface shows it. If the keeper balance falls below a threshold it stops rather than failing mid-transaction, and says so.

---

## 7. FRONTEND ARCHITECTURE

Next.js on Vercel. Wallet connection through wagmi and viem. All portfolio state is read directly from chain at request time, never cached across requests, never stored.

### 7.1 The one endpoint that must exist

`POST /api/quote` — a serverless proxy to the OKX DEX aggregator. The API key lives in Vercel environment variables and never reaches the browser. Takes token in, token out and amount; returns the quote, the route and the estimated output. Rate limited by IP.

This exists solely because the key cannot be public. Everything else the frontend needs is on chain or in the repository.

### 7.2 What is read from where

Mandate parameters, cumulative spend, paused state and expiry come from the contract. Token balances come from RPC. Prices and drift come from `/api/quote`. Action history comes from a JSON file in the repository, fetched raw.

No database. No user accounts. The wallet is the identity.

---

## 8. STATE MODEL

Every state below must render as a distinct, legible screen. A state that falls through to a generic error is a bug.

### 8.1 Precedence when states co-occur

Several of these states are independently reachable at the same moment, and the design system permits one red element per screen. The red slot goes to whichever failure most affects the user's money, in this order:

1. **Leg failed** — money moved and something went wrong.
2. **Insufficient allowance** — the agent is blocked, but nothing is at risk.
3. **Keeper stale** — nothing is happening, which is the least urgent of the three.
4. Anything else.

Everything demoted is stated plainly as text in bone at 60 percent. Demoted does not mean hidden: a user must still be able to read every condition currently true, just not in red.

### 8.2 How waiting is shown

Waiting is never animated. In an instrument a wait is a measurement like any other, so it is shown as elapsed or remaining time in mono, counting, with nothing else in motion.

A leg in flight shows seconds elapsed since submission. Waiting for the first cycle shows time until the next scheduled run. Both are precise and honest, and both tell the user more than a spinner could.

**No wallet connected.** The product explains itself and offers to connect. Nothing else is shown as though it were real.

**Wrong network.** Detected and offered as a one-click switch to X Layer. The app does not silently read the wrong chain.

**Connected, no mandate.** The composition flow.

**Mandate created, nothing bought yet.** Target shown, holdings empty, agent has not yet run. Explicitly "waiting for first cycle" rather than an empty dashboard.

**Building.** Some legs executed, some not. Shown as progress toward target with the current distance, never as an error. This is the state that would break a naive implementation and here it is simply an intermediate position.

**Within tolerance.** The steady state. Current weights, target weights, drift for each position, time since last check.

**Drift detected, action pending.** Which position is out, by how much, what the agent intends to do next.

**Executing.** A leg is in flight.

**Leg failed.** Named, with the reason, and the note that the next cycle recomputes from actual state. Not a dead end.

**Cap reached.** Total spend limit hit. The agent will not buy more. The user can raise the cap or leave it.

**Paused.** By the user. Nothing happens until resumed.

**Expired.** The mandate ran past its horizon. Holdings are untouched and belong to the user.

**Revoked.** Permanent. Prompts the user to revoke allowances too, with a direct action.

**Insufficient allowance.** The mandate is valid but the agent cannot act. Shown with a one-click fix.

**Keeper stale.** The agent has not run in longer than expected. Shown honestly with the time since last cycle, because a product that acts on your behalf must tell you when it has stopped.

**Mint paused or token not trading.** If a basket token cannot be traded, the agent refuses and the interface says which one and why.

---

## 9. USER FLOWS

### 9.1 First run

Land, read what it is, connect wallet, switch to X Layer if needed.

Compose the basket: pick from available xStocks on X Layer, set weights, or take a preset. Weights must sum to 100 and the interface enforces it as you type rather than rejecting at the end.

Set the mandate: drift tolerance, maximum single trade, total spend cap, expiry. Each has a sensible default and an explanation of what it bounds. The user should understand that these are limits on what the agent may do, not settings for how it behaves.

Review: a plain-language summary of exactly what is being authorised. "The agent may spend up to X USDC in total, never more than Y in one trade, only to buy tokens that are below their target weight and sell tokens above it, until this date, and you can stop it at any time."

Approve allowances. One transaction per token, or a single approval for USDC if the initial build is buy-only. Explain why each is needed.

Create the mandate. One transaction.

Then wait. The first cycle runs within five minutes and the interface says so.

### 9.2 Ongoing

Open the dashboard: current value, each position with target and actual weight, current drift, last action, next check. The action log below, showing both actions and refusals.

### 9.3 Changing the mandate

Adjust weights, tolerance or cap. Each is a transaction. The interface shows what changes and what it means.

### 9.4 Exit

Pause stops the agent immediately. Revoke ends the mandate permanently. Separately, the user can sell the basket back to USDC, which is a manual action in this version rather than something the agent does.

---

## 10. INVARIANTS

These must hold and must be tested.

The contract's balance of every token is zero at the end of every transaction.

USDC may only be spent to buy a basket token currently below its target share, and a basket token may only be sold when currently above it. *(This is the checkable form of "no leg makes things worse". The contract enforces direction, not optimality — see 5.2.)*

Cumulative USDC spend never exceeds the mandate's cap.

No single USDC leg exceeds the maximum leg size.

All caps and limits are denominated in USDC, never in a rebasing basket token.

Only the named agent may call execute, and only for mandates that name it.

Only the owner may pause, resume, revoke or amend.

A revoked or expired mandate can never execute again.

Output tokens always land at the owner's address, never anywhere else.

The agent never fires without a fresh quote from the current cycle.

No token amount is cached across a transaction or a cycle. Every balance used in a decision is read fresh at the point of use.

The agent never trades a token inside its multiplier activation window.

Nothing in the interface renders undefined, NaN or null.

---

## 11. FAILURE BEHAVIOUR

For each dependency the default is to do nothing rather than to guess.

RPC unreachable: no action, recorded, interface shows stale.

Quote API unreachable or malformed: no action, recorded.

Quote implies a price far outside the previous cycle's band: no action, recorded as a sanity failure.

Swap reverts: recorded with the revert reason; next cycle recomputes from actual state.

Swap lands but returns less than expected: the real received amount is recorded, not the quoted one.

Actions cron runs late or not at all: the agent counts cycles by what actually happened, never by elapsed time, and the interface shows the true time since last run.

Keeper out of gas: stops cleanly, says so.

---

## 12. OUT OF SCOPE

Lending or using the basket as collateral. Noted as the direction this goes once Aave is live on X Layer, not built.

Multiple concurrent mandates per address.

Selling the whole basket automatically on exit.

Fiat on-ramp.

Any fee taken by Vectra.

Cross-chain anything.

---

## 13. PRE-BUILD VERIFICATIONS

Each of these can invalidate part of the design and each is cheap. Do them before writing the contract.

**Which xStocks exist on X Layer**, with their contract addresses and decimals, pulled from the aggregator rather than assumed. *(In progress. The universe is far larger than this document assumed — hundreds of listings, not a dozen. See 16.)*

**The OKX DEX aggregator router address on X Layer**, and the exact calldata shape its swap endpoint returns, since the contract will be forwarding it.

**Whether the aggregator's swap endpoint permits a recipient other than the caller**, which determines whether output can be sent straight to the user or must pass through the contract.

**Actual gas cost of an execute call on X Layer**, to size the keeper's OKB balance.

**Liquidity across ten different xStocks at five dollars each**, not just NVDAx at one dollar. The thin ones matter more than the liquid one. *(Being answered at far greater scale by the liquidity probe.)*

**The xStocks Assets endpoint**, specifically whether it returns multiplier activation timestamps for X Layer assets and in what form, since section 14 depends on it. *(Unresolved — see 16.)*

**Enough recorded price history to compute tracking error.** The accuracy claim in section 2A needs a price series across the index constituents. Start recording as early as possible, on the same five minute cadence, so the comparison between continuous convergence and monthly or quarterly rebalancing is computed from real data rather than asserted. This is the evidence the submission rests on and it cannot be backfilled.

---

## 14. REBASING, AND WHAT IT CHANGES

Verified against the issuer's documentation. On EVM chains, xStocks are rebasing ERC-20 tokens. Corporate events are applied through an onchain multiplier, and the contract adjusts balances directly, so `balanceOf()` always returns the current equity-adjusted amount. An internal `sharesOf()` holds the constant underlying accounting. Dividends are reinvested and increase balances, splits increase them proportionally, reverse splits decrease them. No action is required from holders.

This is the opposite of the Solana implementation, where the raw balance stays constant and applications must apply a stored multiplier themselves.

**Confirmed on chain.** NVDAx at `0xc845b2894dbddd03858fd2d643b4ef725fe0849d` exposes `multiplier()` returning an 18-decimal fixed-point value, read live at 1.001701196801074. `getMultiplier()`, `currentMultiplier()`, `scalingFactor()` and `totalShares()` all revert. Rebasing is live, not theoretical — the multiplier has already moved above 1.

### 14.1 Reference cases, recorded live

Both kinds of corporate event are already visible on X Layer. These are recorded here as of 2026-09-17 because they are demonstrable rather than described, and because a multiplier can change at any time and these readings cannot be recovered afterwards.

| Token | Multiplier | What it evidences |
|---|---|---|
| **CRWDx** | `4.0` | A four-for-one split, already applied on chain. The clean split case. |
| **CMCSAx** | `1.0876797409606038` | Dividend accrual of roughly 8.8% since issuance. |
| **CVXx** | `1.0295541831890767` | Dividend accrual of roughly 3.0%. |
| NVDAx | `1.001701196801074` | Early accrual, the baseline case. |

CRWDx is the important one. A 4.0 multiplier means a holder's `balanceOf` is four times their `sharesOf`, and any system that cached a balance across that event was wrong by 300%. It turns section 14 from a description of a mechanism into something that can be pointed at.

These are also the natural demo assets: a basket containing CRWDx and CMCSAx exercises both event types against real state rather than a simulated rebase.

**What this makes easy.** A split does not create a false price collapse. One token continues to track one share, so on a ten for one split the token price falls to a tenth while the balance rises tenfold and the position's value is unchanged. Drift computed as balance times price remains correct through the event with no special handling. The failure mode that requires an explicit guard on Solana does not exist here.

**What this makes dangerous.** Balances change without any transfer occurring. Any value cached across a cycle, stored as a number, or read at one moment and used at another can be silently wrong. So:

Never store a token amount and reuse it. Read `balanceOf` fresh at the point of use, inside the same transaction where it matters.

Never assume the balance after a transfer equals the balance before minus the amount sent. Assert against a fresh read.

Where an amount must survive across time, use `sharesOf` rather than `balanceOf`, since shares are the invariant quantity.

Treat the mandate's cumulative spend cap in USDC terms, which does not rebase, rather than in token terms, which does.

**The issuer's own instruction.** The technical overview recommends that trading venues and protocols pause all interactions with the token for a brief window, several minutes, before and after each multiplier activation timestamp. Current and historical multiplier values and their activation timestamps are available through the Assets endpoints.

The agent therefore reads those timestamps each cycle and refuses to trade any token inside its activation window, recording the refusal with the token and the window. This is a documented issuer requirement that almost no integration will honour, and honouring it is cheap.

---

## 15. BUILD ORDER

Verifications first. Then the contract, tested against a Foundry fork of X Layer mainnet with real xStocks and real routing, including a forced rebase to confirm nothing caches a balance. Then the agent against the deployed contract on a live mandate funded with a few dollars. Then the frontend. Then the adversarial audit. Then the demo recording.

The contract is deployed once and not redeployed after the agent is working, so leave it until the verifications are complete.

---

## 16. OPEN ITEMS

Recorded as they are found, so the document does not quietly diverge from what is known.

**Activation timestamps are not currently obtainable.** `api.backed.fi` is reachable but no asset route was discoverable, and the published documentation is client-rendered and could not be retrieved. The recorder samples `multiplier()` every five minutes, so a corporate event is detectable *after* it occurs, which is sufficient for interpreting the price series. It is not sufficient for section 14's requirement that the agent refuse to trade *before* activation. **This blocks that invariant, not the recorder.**

**Unknown selectors may return data instead of reverting.** The NVDAx proxy returned 36 bytes of padded garbage for `getCurrentMultiplier()`, decoding to an absurd value rather than reverting. Any `eth_call` in this system must validate return length and range before trusting a result. On this chain, "it returned data" does not mean "it implemented the function".

**The universe is much larger than assumed.** X Layer lists hundreds of xStocks. Section 9.1's "pick from available xStocks" is not a workable interface at that scale, and "choose ten by liquidity" is no longer an obvious selection rule. This strengthens section 2A's position that baskets should be defined indices, and that decision should be taken with the liquidity probe results in hand.

**OKX's edge rejects default HTTP clients.** Requests carrying a library default user agent are refused by Cloudflare with error 1010 before reaching the API. Clients must send ordinary browser headers. If this escalates to TLS fingerprinting, the correct response is to adopt OKX's own SDK rather than push further against the edge.

**Depth is measured, not read from a field.** The aggregator returns `priceImpactPercentage` as null on this chain, so the original plan to rank constituents by reported price impact could not work. Depth is instead observed directly: quote the same token at one dollar and at fifty, and read how far the rate degrades between them. This is a better method than the one it replaces, not merely a workaround — it is a direct observation of what the book does under size, rather than a number the venue reports about itself, and it cannot be misreported. The same technique settled the price-unit question on Gapless.

**A refusal is not a liquidity finding.** An early probe at 1.1 second spacing returned a success pattern inconsistent with real markets — TSLAx dead while DELLx quoted — which indicates throttling rather than market depth. Probe outcomes are therefore recorded in three categories that never share a column: `quotable`, `no_route` (a genuine finding about the token), and `unknown` (the API refused us: 429, a rate-limit code, or a transport error). Unknowns are retried on every subsequent run and are never counted as evidence about liquidity. Request spacing defaults to 3 seconds and is raised if refusals persist.

**Liquidity lives in wrapped, non-rebasing versions of the tokens.** Routes on the quotable set resolve as `Uniswap V4 | Uniswap V3 | xStocks wrap V2`. Investigating on chain: an address holding 2,481 NVDAx turned out to be `wNVDAx`, "Wrapped NVIDIA xStock", an ERC-4626 style vault whose `asset()` returns the NVDAx address. So the AMM pools hold the *wrapper*, and the aggregator wraps and unwraps around the swap. The rebasing token itself is not what trades.

Consequences: liquidity is AMM rather than RFQ, so depth is observable on chain independently of the aggregator; and an xStock with no wrapper deployed cannot be routed at any size, which is the most likely explanation for the 594. The wrappers are **not** in the aggregator's own token list — 662 tokens on chain, 640 of them xStocks, and `wNVDAx` is absent — so wrapper discovery needs either event logs or the swap payload's route data.

**Depth, measured.** Rate degradation between a $1 and a $50 quote: SPYx 0.0002%, QQQx 0.0005%, NVDAx 0.0009%, TSLAx 0.0021%, AAPLx 0.0021%. The thin tail: MRNAx 0.30%, RDDTx 0.44%, RKLBx 1.93%, IRENx 2.14%, NKEx 2.92%. Combined with the flat 0.25% service fee and a zero network fee, the complete statement is measurable: total cost is a constant percentage plus slippage that barely moves with size. **Keep the thin tail in the submission** — a spread from 0.0002% to 2.92% is what makes the figure credible rather than curated.

**X Layer's public RPC caps `eth_getLogs` at 100 blocks.** Historic log scanning is therefore impractical against 70.9M blocks, and the public alternatives are either Cloudflare-blocked or restrict ranges on their free tier. Any on-chain archaeology must be targeted rather than swept.

**A concurrency group with `cancel-in-progress: false` drops pending runs rather than queueing them.** Sharing one group between the recorder and discovery silently cost 97% of a day's price series. Workflows that must not miss a tick get their own group.

**Scheduled runs are irregular.** GitHub's five minute cron is a floor, not a guarantee; runs are delayed or dropped under load, and schedules auto-disable after sixty days of repository inactivity. The recorder buckets and dedupes readings so jitter is absorbed, but the tracking error computation must treat the series as irregularly sampled rather than assuming 288 readings per day.
