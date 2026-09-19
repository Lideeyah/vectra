// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";

/// @notice Shares are the quantity that survives a rebase. balanceOf() does not.
interface IRebasingERC20 is IERC20 {
    function sharesOf(address account) external view returns (uint256);
}

/**
 * @title VectraMandate
 * @notice A user-signed mandate bounding what an agent may do with their tokens.
 *
 * The contract never holds a balance between transactions. It pulls exactly what
 * a leg requires, swaps through a fixed router, forwards the output to the
 * mandate owner, and asserts it holds nothing at the end of every call. If this
 * contract is completely broken, the loss is bounded by the allowance one user
 * granted — nothing more.
 *
 * WHAT THIS CONTRACT DOES NOT DO
 *
 * It has no oracle and does not want one. Distance from target is defined in
 * weight space and weights require prices, so the contract cannot compute
 * portfolio distance and cannot prove that a leg is the optimal next step. That
 * computation is the agent's, off chain, and is not verified here.
 *
 * What the contract bounds is the SIZE and DIRECTION of trades:
 *   - spend is capped in USDC, per leg and in total
 *   - USDC may only buy a token whose share balance is below its target
 *   - a basket token may only be sold when its share balance is above target
 *
 * A compromised agent therefore retains freedom to choose a suboptimal but
 * still corrective leg. What it cannot do is churn the position, buy what is
 * already at or above target, or spend beyond the cap. That is a weaker
 * guarantee than "every action reduces distance from target", and it is stated
 * plainly rather than glossed.
 *
 * WHY TARGETS ARE IN SHARES
 *
 * xStocks on X Layer are rebasing: a corporate event changes balanceOf() with
 * no transfer occurring, while sharesOf() stays constant. CRWDx currently sits
 * at a multiplier of 4.0, so a holder's balance is four times their shares. A
 * target expressed in balance terms would silently change meaning the moment a
 * multiplier activated. Targets are therefore absolute share quantities, set by
 * the owner, and are the only quantity the direction rule consults.
 *
 * The consequence, stated openly: the contract's notion of "target" is a share
 * quantity, which is a proxy for the value weights the product actually cares
 * about, and it drifts from those weights as prices move. Re-targeting is an
 * owner action, not something the agent may do.
 */
contract VectraMandate is ReentrancyGuard {
    using SafeERC20 for IERC20;

    uint16 public constant BPS = 10_000;
    uint256 public constant MAX_BASKET = 10;
    uint64 public constant MAX_HORIZON = 365 days;
    uint256 public constant MAX_SWEEP = 8;

    /// @notice The contract must retain nothing of economic value after a call.
    ///         Exact zero is not always reachable: balanceOf on a rebasing token
    ///         is derived by integer division (shares * multiplier / 1e18), so
    ///         transferring the full balance rounds the share conversion down
    ///         and can leave a wei or two behind. Found by a fork test against
    ///         real NVDAx, whose multiplier is 1.0017 rather than the mocks'
    ///         exact 1e18. At 18 decimals this bound is ~1e-15 of a token —
    ///         fractions of a nanocent — and it is a ceiling, not an allowance.
    uint256 public constant DUST_WEI = 1000;

    /// @notice The aggregator contract this mandate may call. Immutable by design.
    address public immutable router;
    /// @notice The address allowances are granted to. On OKX this is frequently
    ///         NOT the same as the call target, so it is stored separately
    ///         rather than assumed equal.
    address public immutable spender;
    /// @notice The accounting unit. Does not rebase, so all caps are denominated in it.
    address public immutable usdc;

    /// @notice Creation parameters. A struct rather than a parameter list so the
    ///         frontend constructs one object, and so adding a field later does
    ///         not reshape a positional signature — which cannot be changed
    ///         after deployment.
    struct MandateParams {
        address[] tokens;
        uint16[] weightsBps;
        uint256[] targetShares;
        uint16 driftBps;
        uint256 maxLegUsdc;
        uint256 totalCapUsdc;
        uint64 expiry;
        address agent;
    }

    struct Mandate {
        address owner;
        address agent;
        uint64 expiry;
        bool paused;
        bool revoked;
        uint16 driftBps;
        uint256 maxLegUsdc;
        uint256 totalCapUsdc;
        uint256 spentUsdc;
        address[] tokens;
        uint16[] weightsBps;      // recorded for the agent and the interface
        uint256[] targetShares;   // the enforceable target
    }

    mapping(uint256 => Mandate) private _mandates;
    mapping(address => uint256) public activeMandateOf;
    uint256 public nextMandateId = 1;

    event MandateCreated(uint256 indexed id, address indexed owner, address indexed agent);
    event Executed(
        uint256 indexed id, address tokenIn, address tokenOut,
        uint256 amountIn, uint256 amountOut
    );
    event Paused(uint256 indexed id, bool paused);
    event Revoked(uint256 indexed id);
    event TargetsAmended(uint256 indexed id);
    event CapsAmended(uint256 indexed id, uint256 maxLegUsdc, uint256 totalCapUsdc);

    error NotOwner();
    error NotAgent();
    error MandateInactive();
    error BadBasket();
    error BadWeights();
    error BadExpiry();
    error AlreadyHasMandate();
    error TokenNotInBasket();
    error SameToken();
    error LegTooLarge();
    error CapExceeded();
    error WrongDirection();
    error InsufficientOutput();
    error ContractRetainedFunds();

    constructor(address router_, address spender_, address usdc_) {
        if (router_ == address(0) || spender_ == address(0) || usdc_ == address(0)) {
            revert BadBasket();
        }
        router = router_;
        spender = spender_;
        usdc = usdc_;
    }

    // ---------------------------------------------------------------- mandate

    function createMandate(MandateParams calldata p) external returns (uint256 id) {
        _validate(p);

        id = nextMandateId++;
        Mandate storage m = _mandates[id];
        m.owner = msg.sender;
        m.agent = p.agent;
        m.expiry = p.expiry;
        m.driftBps = p.driftBps;
        m.maxLegUsdc = p.maxLegUsdc;
        m.totalCapUsdc = p.totalCapUsdc;
        m.tokens = p.tokens;
        m.weightsBps = p.weightsBps;
        m.targetShares = p.targetShares;

        activeMandateOf[msg.sender] = id;
        emit MandateCreated(id, msg.sender, p.agent);
    }

    function _validate(MandateParams calldata p) private view {
        uint256 n = p.tokens.length;
        if (n == 0 || n > MAX_BASKET) revert BadBasket();
        if (p.weightsBps.length != n || p.targetShares.length != n) revert BadBasket();
        if (p.agent == address(0) || p.maxLegUsdc == 0 || p.totalCapUsdc == 0) {
            revert BadBasket();
        }
        if (p.driftBps == 0 || p.driftBps > BPS) revert BadWeights();
        if (p.expiry <= block.timestamp || p.expiry > block.timestamp + MAX_HORIZON) {
            revert BadExpiry();
        }
        if (activeMandateOf[msg.sender] != 0) revert AlreadyHasMandate();

        uint256 sum;
        for (uint256 i; i < n; ++i) {
            address t = p.tokens[i];
            if (t == address(0) || t == usdc) revert BadBasket();
            // Reject duplicates: a repeated token would make the direction rule
            // ambiguous about which target applies.
            for (uint256 j; j < i; ++j) {
                if (p.tokens[j] == t) revert BadBasket();
            }
            sum += p.weightsBps[i];
        }
        if (sum != BPS) revert BadWeights();
    }

    // ---------------------------------------------------------------- execute

    /**
     * @notice Execute one leg. Callable only by the mandate's named agent.
     * @param routerCalldata Swap calldata obtained from the aggregator this cycle.
     *        Forwarded verbatim to `router` and never constructed here.
     */
    /**
     * @param sweep Intermediate tokens the route passes through, which the
     *        contract must not be left holding. Routes on this chain go through
     *        wrapped, non-rebasing versions of the xStocks — a USDC to NVDAx
     *        swap touches wNVDAx — so asserting only on tokenIn and tokenOut
     *        would pass while the contract still held wrapper dust.
     *
     *        Declaring a token here can only cause its balance to be sent to
     *        the mandate owner, so a malicious agent gains nothing by adding
     *        entries. Omitting one is the risk, and it is the agent's job to
     *        declare every token in the route it just quoted.
     */
    function execute(
        uint256 id,
        address tokenIn,
        address tokenOut,
        uint256 amountIn,
        uint256 minOut,
        bytes calldata routerCalldata,
        address[] calldata sweep
    ) external nonReentrant {
        Mandate storage m = _mandates[id];
        if (m.owner == address(0) || m.revoked || m.paused) revert MandateInactive();
        if (block.timestamp >= m.expiry) revert MandateInactive();
        if (msg.sender != m.agent) revert NotAgent();
        if (tokenIn == tokenOut) revert SameToken();
        if (amountIn == 0) revert LegTooLarge();

        _checkSizeAndDirection(m, tokenIn, tokenOut, amountIn);

        address owner_ = m.owner;

        // Pull exactly what this leg requires, straight from the owner.
        IERC20(tokenIn).safeTransferFrom(owner_, address(this), amountIn);

        // Approve only the spender, only for this leg, and only this amount.
        IERC20(tokenIn).forceApprove(spender, amountIn);

        // ---------------------------------------------------------------
        // VERIFIED against a live X Layer swap payload (data/verifications/swap.json):
        //   call target  0x7c5bee2a8091c3ef39072f64f18fac913060aeaf
        //   spender      0x8b773D83bc66Be128c60e07E17C8901f7a64F000
        //   selector     0xf2c42696, 3076 bytes, tx.value 0, gas ~550k
        // The two addresses DIFFER, which is why they are separate immutables.
        //
        // The agent must request the payload with userWalletAddress set to THIS
        // contract, not the mandate owner: the calldata encodes its caller, and
        // a payload built for the owner's address will not work when the
        // contract is the one calling.
        // ---------------------------------------------------------------
        (bool ok, bytes memory ret) = router.call(routerCalldata);
        if (!ok) {
            assembly ("memory-safe") {
                revert(add(ret, 0x20), mload(ret))
            }
        }

        // Clear any residual approval regardless of what the router consumed.
        IERC20(tokenIn).forceApprove(spender, 0);

        (uint256 received, uint256 leftover) =
            _settle(owner_, tokenIn, tokenOut, minOut, sweep);

        if (tokenIn == usdc) {
            // Cap counts what was actually spent, not what was requested.
            m.spentUsdc += amountIn - leftover;
        }

        emit Executed(id, tokenIn, tokenOut, amountIn, received);
    }

    /**
     * @dev Post-swap settlement. Nothing here is computed as a delta: a rebase
     *      can move balances mid-transaction with no transfer, so every amount
     *      is read from what the contract actually holds at that moment.
     *
     *      Sweeping covers route intermediates — the wrapped, non-rebasing
     *      versions the xStock pools actually hold. The invariant is enforced
     *      over the declared set; the EVM cannot enumerate every token, so an
     *      intermediate the agent fails to declare is the residual risk.
     */
    function _settle(
        address owner_,
        address tokenIn,
        address tokenOut,
        uint256 minOut,
        address[] calldata sweep
    ) private returns (uint256 received, uint256 leftover) {
        received = IERC20(tokenOut).balanceOf(address(this));
        if (received < minOut) revert InsufficientOutput();
        IERC20(tokenOut).safeTransfer(owner_, received);

        leftover = IERC20(tokenIn).balanceOf(address(this));
        if (leftover != 0) IERC20(tokenIn).safeTransfer(owner_, leftover);

        uint256 n = sweep.length;
        if (n > MAX_SWEEP) revert BadBasket();
        for (uint256 i; i < n; ++i) {
            address s = sweep[i];
            if (s == tokenIn || s == tokenOut) continue;
            uint256 stuck = IERC20(s).balanceOf(address(this));
            if (stuck != 0) IERC20(s).safeTransfer(owner_, stuck);
        }

        if (IERC20(tokenIn).balanceOf(address(this)) > DUST_WEI
            || IERC20(tokenOut).balanceOf(address(this)) > DUST_WEI) {
            revert ContractRetainedFunds();
        }
        for (uint256 i; i < n; ++i) {
            if (IERC20(sweep[i]).balanceOf(address(this)) > DUST_WEI) {
                revert ContractRetainedFunds();
            }
        }
    }

    /// @dev Size and direction are all the contract can check without prices.
    function _checkSizeAndDirection(
        Mandate storage m,
        address tokenIn,
        address tokenOut,
        uint256 amountIn
    ) private view {
        if (tokenIn == usdc) {
            // Buying a basket token with USDC.
            uint256 idx = _indexOf(m, tokenOut);
            if (amountIn > m.maxLegUsdc) revert LegTooLarge();
            if (m.spentUsdc + amountIn > m.totalCapUsdc) revert CapExceeded();
            if (_shares(tokenOut, m.owner) >= m.targetShares[idx]) revert WrongDirection();
        } else if (tokenOut == usdc) {
            // Selling a basket token back to USDC.
            uint256 idx = _indexOf(m, tokenIn);
            if (_shares(tokenIn, m.owner) <= m.targetShares[idx]) revert WrongDirection();
        } else {
            // Token-to-token legs are not permitted: neither side is the
            // accounting unit, so neither cap nor direction is checkable.
            revert TokenNotInBasket();
        }
    }

    /**
     * @dev Share balance, which is invariant under a rebase.
     *      Falls back to balanceOf only if sharesOf is absent — verified present
     *      on NVDAx, TSLAx, AAPLx and CRWDx, but a basket is owner-chosen and a
     *      non-rebasing token would not implement it.
     */
    function _shares(address token, address account) private view returns (uint256) {
        (bool ok, bytes memory ret) = token.staticcall(
            abi.encodeCall(IRebasingERC20.sharesOf, (account))
        );
        // A correct uint256 return is exactly 32 bytes. Some proxies on this
        // chain return padded data for unimplemented selectors instead of
        // reverting, so length is checked rather than trusted.
        if (ok && ret.length == 32) {
            return abi.decode(ret, (uint256));
        }
        return IERC20(token).balanceOf(account);
    }

    function _indexOf(Mandate storage m, address token) private view returns (uint256) {
        uint256 n = m.tokens.length;
        for (uint256 i; i < n; ++i) {
            if (m.tokens[i] == token) return i;
        }
        revert TokenNotInBasket();
    }

    // ----------------------------------------------------------------- owner

    modifier onlyMandateOwner(uint256 id) {
        if (_mandates[id].owner != msg.sender) revert NotOwner();
        _;
    }

    function pause(uint256 id) external onlyMandateOwner(id) {
        _mandates[id].paused = true;
        emit Paused(id, true);
    }

    function resume(uint256 id) external onlyMandateOwner(id) {
        if (_mandates[id].revoked) revert MandateInactive();
        _mandates[id].paused = false;
        emit Paused(id, false);
    }

    /// @notice Permanent. Moves no funds, because the contract holds none.
    ///         The owner must separately revoke their ERC-20 allowances.
    function revoke(uint256 id) external onlyMandateOwner(id) {
        Mandate storage m = _mandates[id];
        m.revoked = true;
        activeMandateOf[msg.sender] = 0;
        emit Revoked(id);
    }

    function amendTargets(uint256 id, uint256[] calldata targetShares)
        external
        onlyMandateOwner(id)
    {
        Mandate storage m = _mandates[id];
        if (m.revoked) revert MandateInactive();
        if (targetShares.length != m.tokens.length) revert BadBasket();
        m.targetShares = targetShares;
        emit TargetsAmended(id);
    }

    function amendCaps(uint256 id, uint256 maxLegUsdc, uint256 totalCapUsdc)
        external
        onlyMandateOwner(id)
    {
        Mandate storage m = _mandates[id];
        if (m.revoked) revert MandateInactive();
        if (maxLegUsdc == 0 || totalCapUsdc < m.spentUsdc) revert BadBasket();
        m.maxLegUsdc = maxLegUsdc;
        m.totalCapUsdc = totalCapUsdc;
        emit CapsAmended(id, maxLegUsdc, totalCapUsdc);
    }

    // ----------------------------------------------------------------- views

    function mandate(uint256 id)
        external
        view
        returns (
            address owner_, address agent, uint64 expiry, bool paused, bool revoked,
            uint16 driftBps, uint256 maxLegUsdc, uint256 totalCapUsdc, uint256 spentUsdc
        )
    {
        Mandate storage m = _mandates[id];
        return (m.owner, m.agent, m.expiry, m.paused, m.revoked,
                m.driftBps, m.maxLegUsdc, m.totalCapUsdc, m.spentUsdc);
    }

    function basket(uint256 id)
        external
        view
        returns (address[] memory tokens, uint16[] memory weightsBps, uint256[] memory targetShares)
    {
        Mandate storage m = _mandates[id];
        return (m.tokens, m.weightsBps, m.targetShares);
    }

    /// @notice Current share balances against target, in share terms.
    function position(uint256 id)
        external
        view
        returns (address[] memory tokens, uint256[] memory currentShares, uint256[] memory targetShares)
    {
        Mandate storage m = _mandates[id];
        uint256 n = m.tokens.length;
        tokens = m.tokens;
        targetShares = m.targetShares;
        currentShares = new uint256[](n);
        for (uint256 i; i < n; ++i) {
            currentShares[i] = _shares(m.tokens[i], m.owner);
        }
    }

    function isActive(uint256 id) external view returns (bool) {
        Mandate storage m = _mandates[id];
        return m.owner != address(0) && !m.revoked && !m.paused
            && block.timestamp < m.expiry && m.spentUsdc < m.totalCapUsdc;
    }
}
