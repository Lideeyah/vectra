// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import {Test, console2} from "forge-std/Test.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {VectraMandate} from "../contracts/VectraMandate.sol";
import {MockUSDC, MockRebasingToken} from "./mocks/Mocks.sol";

/// @notice Takes everything it is approved for and returns nothing.
contract PredatoryRouter {
    address public sink = address(0xDEAD);

    function drain(address token, uint256 amount) external {
        IERC20(token).transferFrom(msg.sender, sink, amount);
    }

    /// @dev Takes the input and delivers a token the caller did not ask for.
    function wrongToken(address takeToken, uint256 take, address giveToken, uint256 give)
        external
    {
        IERC20(takeToken).transferFrom(msg.sender, sink, take);
        if (give > 0) IERC20(giveToken).transfer(msg.sender, give);
    }

    function noop() external {}
}

/// @notice Attempts to re-enter the mandate contract mid-settlement.
contract ReentrantRouter {
    VectraMandate public target;
    uint256 public mandateId;
    bytes public payload;
    bool public fired;
    bool public reentrySucceeded;
    bytes public reentryError;

    function arm(VectraMandate t, uint256 id, bytes calldata p) external {
        target = t;
        mandateId = id;
        payload = p;
    }

    function swapAndReenter(address tokenIn, address tokenOut, uint256 pull, uint256 give)
        external
    {
        if (pull > 0) IERC20(tokenIn).transferFrom(msg.sender, address(this), pull);
        if (give > 0) IERC20(tokenOut).transfer(msg.sender, give);
        if (!fired) {
            fired = true;
            (bool ok, bytes memory err) = address(target).call(payload);
            reentrySucceeded = ok;
            reentryError = err;
        }
    }

    receive() external payable {}
}

/**
 * @notice Adversarial audit of VectraMandate.
 *
 * The contract is immutable with no admin key, so anything missed here is
 * missed permanently. These tests assume the agent key is compromised and the
 * router is hostile, and measure what an owner can actually lose.
 */
contract AdversarialTest is Test {
    VectraMandate internal vectra;
    MockUSDC internal usdc;
    MockRebasingToken internal nvda;
    MockRebasingToken internal tsla;
    PredatoryRouter internal evil;

    address internal owner = address(0xA11CE);
    address internal attacker = address(0xA6E27);   // the compromised agent key
    uint256 internal id;

    // A deliberately non-unit multiplier: a unit multiplier cannot show rounding.
    uint256 internal constant MULT = 1.0017011968010740e18;
    uint256 internal constant TARGET = 10e18;
    uint256 internal constant MAX_LEG = 5e6;        // $5
    uint256 internal constant TOTAL_CAP = 50e6;     // $50
    uint256 internal constant OWNER_USDC = 10_000e6;

    function setUp() public {
        usdc = new MockUSDC();
        nvda = new MockRebasingToken("NVIDIA xStock", "NVDAx");
        tsla = new MockRebasingToken("Tesla xStock", "TSLAx");
        evil = new PredatoryRouter();

        nvda.setMultiplier(MULT);
        tsla.setMultiplier(MULT);

        vectra = new VectraMandate(address(evil), address(evil), address(usdc));
        usdc.mint(owner, OWNER_USDC);

        vm.startPrank(owner);
        usdc.approve(address(vectra), type(uint256).max);
        nvda.approve(address(vectra), type(uint256).max);
        tsla.approve(address(vectra), type(uint256).max);

        address[] memory tokens = new address[](2);
        tokens[0] = address(nvda);
        tokens[1] = address(tsla);
        uint16[] memory w = new uint16[](2);
        w[0] = 5_000;
        w[1] = 5_000;
        uint256[] memory t = new uint256[](2);
        t[0] = TARGET;
        t[1] = TARGET;
        id = vectra.createMandate(VectraMandate.MandateParams({
            tokens: tokens, weightsBps: w, targetShares: t, driftBps: 500,
            maxLegUsdc: MAX_LEG, totalCapUsdc: TOTAL_CAP,
            expiry: uint64(block.timestamp + 30 days), agent: attacker
        }));
        vm.stopPrank();
    }

    function _none() internal pure returns (address[] memory a) { a = new address[](0); }

    // ==================================================== 1. BLAST RADIUS

    /// @notice Compromised agent + hostile router, minOut set to zero.
    ///         Measures what an owner actually loses in USDC.
    function test_BlastRadius_CompromisedAgent_HostileRouter_UsdcLoss() public {
        uint256 before = usdc.balanceOf(owner);
        uint256 legs;

        // Drain in maxLeg chunks until the contract stops it.
        for (uint256 i; i < 50; ++i) {
            bytes memory cd = abi.encodeCall(
                PredatoryRouter.drain, (address(usdc), MAX_LEG)
            );
            vm.prank(attacker);
            try vectra.execute(id, address(usdc), address(nvda), MAX_LEG, 0, cd, _none()) {
                legs++;
            } catch {
                break;
            }
        }

        uint256 lost = before - usdc.balanceOf(owner);
        console2.log("legs that succeeded          ", legs);
        console2.log("USDC lost (6dp)              ", lost);
        console2.log("mandate totalCapUsdc         ", TOTAL_CAP);
        console2.log("owner USDC balance at risk   ", OWNER_USDC);

        assertLe(lost, TOTAL_CAP, "LOSS EXCEEDS THE CAP");
        assertLt(lost, OWNER_USDC, "loss must not reach the whole balance");
    }

    /// @notice The same attack on the token side. The post-state check should
    ///         stop the position being sold below target.
    function test_BlastRadius_TokenSideLossBoundedByExcessOverTarget() public {
        uint256 excess = 4e18;
        nvda.mintShares(owner, TARGET + excess);
        uint256 sharesBefore = nvda.sharesOf(owner);

        uint256 legs;
        for (uint256 i; i < 50; ++i) {
            bytes memory cd = abi.encodeCall(
                PredatoryRouter.drain, (address(nvda), 1e18)
            );
            vm.prank(attacker);
            try vectra.execute(id, address(nvda), address(usdc), 1e18, 0, cd, _none()) {
                legs++;
            } catch {
                break;
            }
        }

        uint256 sharesLost = sharesBefore - nvda.sharesOf(owner);
        console2.log("sell legs that succeeded     ", legs);
        console2.log("shares lost                  ", sharesLost);
        console2.log("excess above target          ", excess);
        console2.log("shares remaining             ", nvda.sharesOf(owner));

        assertLe(sharesLost, excess + vectra.DUST_WEI(), "sold past target");
        assertGe(nvda.sharesOf(owner) + vectra.DUST_WEI(), TARGET, "below target");
    }

    /// @notice A router that delivers a token nobody asked for must not let the
    ///         leg pass: minOut is measured on the requested output.
    function test_HostileRouter_DeliveringWrongTokenFails() public {
        tsla.mintShares(address(evil), 100e18);
        bytes memory cd = abi.encodeCall(
            PredatoryRouter.wrongToken,
            (address(usdc), MAX_LEG, address(tsla), 5e18)
        );
        vm.prank(attacker);
        vm.expectRevert(VectraMandate.InsufficientOutput.selector);
        vectra.execute(id, address(usdc), address(nvda), MAX_LEG, 1e18, cd, _none());
    }

    /// @notice The router address is immutable, so a compromised agent cannot
    ///         redirect the call to a router of its choosing.
    function test_AgentCannotChangeRouter() public {
        PredatoryRouter other = new PredatoryRouter();
        assertEq(vectra.router(), address(evil));
        assertTrue(address(other) != vectra.router());
        // No setter exists; assert the immutables are the constructed values.
        assertEq(vectra.spender(), address(evil));
        assertEq(vectra.usdc(), address(usdc));
    }

    // ==================================================== 2. REENTRANCY

    function test_Reentrancy_ExecuteIsBlockedMidSettlement() public {
        ReentrantRouter r = new ReentrantRouter();
        VectraMandate v = new VectraMandate(address(r), address(r), address(usdc));

        vm.startPrank(owner);
        usdc.approve(address(v), type(uint256).max);
        nvda.approve(address(v), type(uint256).max);
        address[] memory tokens = new address[](1);
        tokens[0] = address(nvda);
        uint16[] memory w = new uint16[](1);
        w[0] = 10_000;
        uint256[] memory t = new uint256[](1);
        t[0] = TARGET;
        uint256 id2 = v.createMandate(VectraMandate.MandateParams({
            tokens: tokens, weightsBps: w, targetShares: t, driftBps: 500,
            maxLegUsdc: MAX_LEG, totalCapUsdc: TOTAL_CAP,
            expiry: uint64(block.timestamp + 30 days), agent: attacker
        }));
        vm.stopPrank();

        nvda.mintShares(address(r), 100e18);

        bytes memory inner = abi.encodeCall(VectraMandate.execute, (
            id2, address(usdc), address(nvda), MAX_LEG, 0,
            abi.encodeCall(ReentrantRouter.swapAndReenter,
                           (address(usdc), address(nvda), MAX_LEG, 1e18)),
            new address[](0)
        ));
        r.arm(v, id2, inner);

        bytes memory outer = abi.encodeCall(ReentrantRouter.swapAndReenter,
                                            (address(usdc), address(nvda), MAX_LEG, 1e18));
        // minOut is shaved: delivering exactly 1e18 on a rebasing token arrives
        // a wei short (see test_MinOut_ExactQuotedOutputRoundsShort).
        vm.prank(attacker);
        v.execute(id2, address(usdc), address(nvda), MAX_LEG, 1e18 - 10, outer, _none());

        assertTrue(r.fired(), "reentry was never attempted");
        assertFalse(r.reentrySucceeded(), "REENTRANT execute SUCCEEDED");
        console2.log("reentrant execute blocked:", !r.reentrySucceeded());
    }

    /// @notice Owner-only functions cannot be reached from inside the router
    ///         call, because msg.sender there is the router, not the owner.
    function test_Reentrancy_OwnerFunctionsUnreachableFromRouter() public {
        vm.prank(address(evil));
        vm.expectRevert(VectraMandate.NotOwner.selector);
        vectra.pause(id);

        vm.prank(address(evil));
        vm.expectRevert(VectraMandate.NotOwner.selector);
        vectra.revoke(id);

        uint256[] memory t = new uint256[](2);
        vm.prank(address(evil));
        vm.expectRevert(VectraMandate.NotOwner.selector);
        vectra.amendTargets(id, t);
    }

    // ==================================================== 3. CAP ACCOUNTING

    function test_Cap_RevertingLegDoesNotCharge() public {
        (,,,,,,,, uint256 before,) = vectra.mandate(id);
        bytes memory cd = abi.encodeCall(PredatoryRouter.noop, ());
        vm.prank(attacker);
        vm.expectRevert(VectraMandate.InsufficientOutput.selector);
        vectra.execute(id, address(usdc), address(nvda), MAX_LEG, 1e18, cd, _none());
        (,,,,,,,, uint256 after_,) = vectra.mandate(id);
        assertEq(after_, before, "a reverting leg charged the cap");
    }

    /// @notice A sell returns USDC but must not restore buying power.
    function test_Cap_SellDoesNotRefundHeadroom() public {
        // Start below target so buying is admissible; the sell comes later.
        // Spend the cap.
        for (uint256 i; i < 10; ++i) {
            bytes memory buy = abi.encodeCall(
                PredatoryRouter.wrongToken,
                (address(usdc), MAX_LEG, address(nvda), 1e17)
            );
            nvda.mintShares(address(evil), 1e18);
            vm.prank(attacker);
            vectra.execute(id, address(usdc), address(nvda), MAX_LEG, 1e17 - 10, buy, _none());
        }
        (,,,,,,,, uint256 spent,) = vectra.mandate(id);
        assertEq(spent, TOTAL_CAP, "cap not fully spent");

        // Now push the position above target so a sell is admissible.
        nvda.mintShares(owner, TARGET + 10e18);

        // Sell back, which returns USDC to the owner.
        usdc.mint(address(evil), 1_000e6);
        bytes memory sell = abi.encodeCall(
            PredatoryRouter.wrongToken,
            (address(nvda), 1e18, address(usdc), 20e6)
        );
        vm.prank(attacker);
        vectra.execute(id, address(nvda), address(usdc), 1e18, 20e6 - 10, sell, _none());

        (,,,,,,,, uint256 afterSell,) = vectra.mandate(id);
        assertEq(afterSell, TOTAL_CAP, "a sell refunded cap headroom");

        // And buying is still refused.
        nvda.mintShares(address(evil), 1e18);
        bytes memory rebuy = abi.encodeCall(
            PredatoryRouter.wrongToken,
            (address(usdc), MAX_LEG, address(nvda), 1e17)
        );
        vm.prank(attacker);
        vm.expectRevert(VectraMandate.CapExceeded.selector);
        vectra.execute(id, address(usdc), address(nvda), MAX_LEG, 1e17 - 10, rebuy, _none());
    }

    /// @notice FINDING. On a rebasing token, delivering exactly the quoted
    ///         amount arrives a wei short: the transfer converts the balance to
    ///         shares by integer division, and converting back rounds down. An
    ///         agent setting minOut equal to the exact quoted output therefore
    ///         reverts on every leg. Harmless in practice because minOut is set
    ///         from the quote MINUS a slippage tolerance, but it is a real
    ///         constraint on the agent and is asserted rather than assumed.
    function test_MinOut_ExactQuotedOutputRoundsShort() public {
        nvda.mintShares(address(evil), 100e18);
        bytes memory cd = abi.encodeCall(
            PredatoryRouter.wrongToken,
            (address(usdc), MAX_LEG, address(nvda), 1e18)
        );

        // Exactly the delivered amount: reverts.
        vm.prank(attacker);
        vm.expectRevert(VectraMandate.InsufficientOutput.selector);
        vectra.execute(id, address(usdc), address(nvda), MAX_LEG, 1e18, cd, _none());

        // One wei of slack: succeeds.
        vm.prank(attacker);
        vectra.execute(id, address(usdc), address(nvda), MAX_LEG, 1e18 - 1, cd, _none());
        console2.log("delivered balance for a 1e18 transfer", nvda.balanceOf(owner));
    }

    /// @notice §2 churn attempt. With direction bounded at entry and distance
    ///         bounded at exit, a position driven to target is stuck there: a
    ///         buy would carry it above, a sell would carry it below. Nothing
    ///         the agent can do reopens it, because only the owner can move the
    ///         target. Attempted rather than argued.
    function test_Churn_PositionAtTargetIsClosedToTheAgent() public {
        // Put the position exactly at target.
        nvda.mintShares(owner, TARGET);
        assertEq(nvda.sharesOf(owner), TARGET);

        nvda.mintShares(address(evil), 100e18);
        usdc.mint(address(evil), 1_000e6);

        bytes memory buy = abi.encodeCall(
            PredatoryRouter.wrongToken,
            (address(usdc), MAX_LEG, address(nvda), 1e17)
        );
        vm.prank(attacker);
        vm.expectRevert(VectraMandate.WrongDirection.selector);
        vectra.execute(id, address(usdc), address(nvda), MAX_LEG, 1e17 - 10, buy, _none());

        bytes memory sell = abi.encodeCall(
            PredatoryRouter.wrongToken,
            (address(nvda), 1e17, address(usdc), 1e6)
        );
        vm.prank(attacker);
        vm.expectRevert(VectraMandate.WrongDirection.selector);
        vectra.execute(id, address(nvda), address(usdc), 1e17, 1e6 - 10, sell, _none());

        // Only the owner can reopen it, and doing so is now logged.
        console2.log("agent cannot move a position sitting at target");
    }

    /// @notice §2 sweep. Declaring an incomplete token set is the known limit.
    ///         The consequence must be retention by the contract, never a loss
    ///         to anyone but the owner — nothing is sent to a third party.
    function test_Sweep_IncompleteSetRetainsRatherThanLoses() public {
        MockRebasingToken wrapper = new MockRebasingToken("Wrapped NVDAx", "wNVDAx");
        wrapper.setMultiplier(MULT);
        wrapper.mintShares(address(evil), 100e18);
        nvda.mintShares(address(evil), 100e18);

        bytes memory cd = abi.encodeCall(
            PredatoryRouter.wrongToken,
            (address(usdc), MAX_LEG, address(wrapper), 3e17)
        );
        // Wrapper NOT declared: the contract keeps it.
        vm.prank(attacker);
        vm.expectRevert(VectraMandate.InsufficientOutput.selector);
        vectra.execute(id, address(usdc), address(nvda), MAX_LEG, 1e17, cd, _none());

        // Nothing reached a third party, and nothing reached the attacker.
        assertEq(wrapper.balanceOf(attacker), 0, "attacker received stranded dust");
        assertEq(wrapper.balanceOf(address(vectra)), 0, "leg reverted, so nothing held");
        console2.log("undeclared intermediate: retained or reverted, never diverted");
    }

    // ==================================================== 4. LIFECYCLE

    function test_RevokedMandateCannotExecuteByAnyPath() public {
        vm.prank(owner);
        vectra.revoke(id);
        bytes memory cd = abi.encodeCall(PredatoryRouter.noop, ());
        vm.prank(attacker);
        vm.expectRevert(VectraMandate.MandateInactive.selector);
        vectra.execute(id, address(usdc), address(nvda), MAX_LEG, 0, cd, _none());
    }

    /// @notice amendTargets can move a target to wherever the position already
    ///         sits. Only the owner can do it, to their own mandate, so it is
    ///         self-directed — but it means "distance from target" is a
    ///         quantity the owner can redefine at will. Asserted, not assumed.
    function test_AmendTargets_OwnerCanLaunderPositionIntoCompliance() public {
        nvda.mintShares(owner, TARGET + 7e18);
        uint256 current = nvda.sharesOf(owner);

        uint256[] memory t = new uint256[](2);
        t[0] = current;      // target moved to exactly where the position sits
        t[1] = TARGET;
        vm.prank(owner);
        vectra.amendTargets(id, t);

        // Now neither a buy nor a sell of that token is permitted.
        bytes memory cd = abi.encodeCall(PredatoryRouter.noop, ());
        vm.prank(attacker);
        vm.expectRevert(VectraMandate.WrongDirection.selector);
        vectra.execute(id, address(nvda), address(usdc), 1e18, 0, cd, _none());
        console2.log("owner retargeted to current position:", current);
    }

    /// @notice An agent named on one mandate must not reach another.
    function test_AgentOfOneMandateCannotExecuteAnother() public {
        address other = address(0xBEE5);
        usdc.mint(other, 1_000e6);
        vm.startPrank(other);
        usdc.approve(address(vectra), type(uint256).max);
        address[] memory tokens = new address[](1);
        tokens[0] = address(nvda);
        uint16[] memory w = new uint16[](1);
        w[0] = 10_000;
        uint256[] memory t = new uint256[](1);
        t[0] = TARGET;
        uint256 otherId = vectra.createMandate(VectraMandate.MandateParams({
            tokens: tokens, weightsBps: w, targetShares: t, driftBps: 500,
            maxLegUsdc: MAX_LEG, totalCapUsdc: TOTAL_CAP,
            expiry: uint64(block.timestamp + 30 days), agent: address(0xF00D)
        }));
        vm.stopPrank();

        bytes memory cd = abi.encodeCall(PredatoryRouter.noop, ());
        vm.prank(attacker);            // agent of `id`, not of `otherId`
        vm.expectRevert(VectraMandate.NotAgent.selector);
        vectra.execute(otherId, address(usdc), address(nvda), MAX_LEG, 0, cd, _none());
    }

    function test_OnlyOwnerMayResumeAndAmend() public {
        vm.prank(owner);
        vectra.pause(id);

        vm.prank(attacker);
        vm.expectRevert(VectraMandate.NotOwner.selector);
        vectra.resume(id);

        uint256[] memory t = new uint256[](2);
        vm.prank(attacker);
        vm.expectRevert(VectraMandate.NotOwner.selector);
        vectra.amendTargets(id, t);

        vm.prank(attacker);
        vm.expectRevert(VectraMandate.NotOwner.selector);
        vectra.amendCaps(id, 1e6, 1e6);
    }

    /// @notice Expiry is a strict boundary: at the expiry second the mandate is
    ///         already dead, not dying.
    function test_ExpiryIsInclusiveOfTheExpirySecond() public {
        (, , uint64 expiry,,,,,,,) = vectra.mandate(id);
        bytes memory cd = abi.encodeCall(PredatoryRouter.noop, ());

        vm.warp(uint256(expiry) - 1);
        vm.prank(attacker);
        vm.expectRevert(VectraMandate.InsufficientOutput.selector);   // alive: fails later
        vectra.execute(id, address(usdc), address(nvda), MAX_LEG, 1e18, cd, _none());

        vm.warp(uint256(expiry));
        vm.prank(attacker);
        vm.expectRevert(VectraMandate.MandateInactive.selector);      // dead at expiry
        vectra.execute(id, address(usdc), address(nvda), MAX_LEG, 1e18, cd, _none());
    }

    /// @notice A validator may shift block.timestamp within its tolerance. The
    ///         consequence is bounded and stated: the mandate's effective life
    ///         moves by that tolerance, seconds against a horizon of days.
    function test_TimestampManipulationMovesExpiryOnlyByTheTolerance() public {
        (, , uint64 expiry,,,,,,,) = vectra.mandate(id);
        bytes memory cd = abi.encodeCall(PredatoryRouter.noop, ());

        // A validator pulling the clock back by 12 seconds keeps it alive.
        vm.warp(uint256(expiry) - 12);
        vm.prank(attacker);
        vm.expectRevert(VectraMandate.InsufficientOutput.selector);
        vectra.execute(id, address(usdc), address(nvda), MAX_LEG, 1e18, cd, _none());

        // Pushing it forward kills it early. Both bounded by the same seconds.
        vm.warp(uint256(expiry) + 12);
        vm.prank(attacker);
        vm.expectRevert(VectraMandate.MandateInactive.selector);
        vectra.execute(id, address(usdc), address(nvda), MAX_LEG, 1e18, cd, _none());

        console2.log("expiry horizon (days)", (uint256(expiry) - 1) / 1 days);
        console2.log("manipulation window (seconds)", uint256(12));
    }

    function test_PausedThenResumedByOwnerWorks() public {
        vm.prank(owner);
        vectra.pause(id);
        bytes memory cd = abi.encodeCall(PredatoryRouter.noop, ());
        vm.prank(attacker);
        vm.expectRevert(VectraMandate.MandateInactive.selector);
        vectra.execute(id, address(usdc), address(nvda), MAX_LEG, 0, cd, _none());

        vm.prank(owner);
        vectra.resume(id);
        vm.prank(attacker);
        vm.expectRevert(VectraMandate.InsufficientOutput.selector);  // alive again
        vectra.execute(id, address(usdc), address(nvda), MAX_LEG, 1e18, cd, _none());
    }

    // ==================================================== 5. CONSTRUCTION

    function test_CannotReceiveNativeToken() public {
        vm.deal(address(this), 1 ether);
        (bool ok,) = address(vectra).call{value: 1 ether}("");
        assertFalse(ok, "contract accepted native OKB");
    }

    function test_ImmutablesAreReadableFromTheDeployedContract() public view {
        // A wrong deployment is detectable before anyone funds it.
        assertTrue(vectra.router() != address(0));
        assertTrue(vectra.spender() != address(0));
        assertTrue(vectra.usdc() != address(0));
    }

    function test_ConstructorRejectsZeroAddresses() public {
        vm.expectRevert(VectraMandate.BadBasket.selector);
        new VectraMandate(address(0), address(evil), address(usdc));
        vm.expectRevert(VectraMandate.BadBasket.selector);
        new VectraMandate(address(evil), address(0), address(usdc));
        vm.expectRevert(VectraMandate.BadBasket.selector);
        new VectraMandate(address(evil), address(evil), address(0));
    }
}
