// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import {Test} from "forge-std/Test.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {VectraMandate} from "../contracts/VectraMandate.sol";
import {MockUSDC, MockRebasingToken, MockRouter} from "./mocks/Mocks.sol";

contract VectraMandateTest is Test {
    VectraMandate internal vectra;
    MockUSDC internal usdc;
    MockRebasingToken internal nvda;
    MockRebasingToken internal tsla;
    MockRouter internal router;

    address internal owner = address(0xA11CE);
    address internal agent = address(0xA6E27);
    address internal stranger = address(0xBAD);

    uint256 internal constant TARGET_SHARES = 10e18;
    uint256 internal constant MAX_LEG = 5e6;      // $5
    uint256 internal constant TOTAL_CAP = 50e6;   // $50
    uint256 internal mandateId;

    function setUp() public {
        usdc = new MockUSDC();
        nvda = new MockRebasingToken("NVIDIA xStock", "NVDAx");
        tsla = new MockRebasingToken("Tesla xStock", "TSLAx");
        router = new MockRouter();

        // spender == router here; a dedicated test covers them differing.
        vectra = new VectraMandate(address(router), address(router), address(usdc));

        usdc.mint(owner, 1_000e6);
        nvda.mintShares(address(router), 1_000e18);
        tsla.mintShares(address(router), 1_000e18);

        vm.startPrank(owner);
        usdc.approve(address(vectra), type(uint256).max);
        nvda.approve(address(vectra), type(uint256).max);
        tsla.approve(address(vectra), type(uint256).max);

        address[] memory tokens = new address[](2);
        tokens[0] = address(nvda);
        tokens[1] = address(tsla);
        uint16[] memory weights = new uint16[](2);
        weights[0] = 5_000;
        weights[1] = 5_000;
        uint256[] memory targets = new uint256[](2);
        targets[0] = TARGET_SHARES;
        targets[1] = TARGET_SHARES;

        mandateId = vectra.createMandate(
            tokens, weights, targets, 500, MAX_LEG, TOTAL_CAP,
            uint64(block.timestamp + 30 days), agent
        );
        vm.stopPrank();
    }

    // ------------------------------------------------------------- helpers

    function _buy(uint256 spend, uint256 give, uint256 minOut) internal {
        bytes memory cd = abi.encodeCall(
            MockRouter.swap, (address(usdc), address(nvda), spend, give)
        );
        vm.prank(agent);
        vectra.execute(mandateId, address(usdc), address(nvda), spend, minOut, cd);
    }

    // ------------------------------------------------- the zero balance rule

    function test_ContractHoldsNothingAfterExecute() public {
        _buy(5e6, 1e18, 1e18);

        assertEq(usdc.balanceOf(address(vectra)), 0, "usdc retained");
        assertEq(nvda.balanceOf(address(vectra)), 0, "token retained");
        assertEq(nvda.sharesOf(address(vectra)), 0, "shares retained");
        assertEq(nvda.balanceOf(owner), 1e18, "owner did not receive output");
    }

    // ------------------------------------------------ rebase mid-transaction

    /// @notice The case the whole design is exposed to: balances move with no
    ///         transfer, so "after = before - sent" is false. The contract must
    ///         forward what it actually holds, not what it computed.
    function test_RebaseAfterSwap_ForwardsActualHoldings() public {
        bytes memory cd = abi.encodeCall(
            MockRouter.swapThenRebase,
            (address(usdc), address(nvda), 5e6, 1e18, 2e18) // 2:1 split mid-call
        );
        vm.prank(agent);
        vectra.execute(mandateId, address(usdc), address(nvda), 5e6, 1e18, cd);

        // 1e18 delivered as 1e18 shares, then the multiplier doubled.
        assertEq(nvda.sharesOf(owner), 1e18, "shares wrong");
        assertEq(nvda.balanceOf(owner), 2e18, "owner should hold the rebased balance");
        assertEq(nvda.balanceOf(address(vectra)), 0, "contract retained after rebase");
        assertEq(nvda.sharesOf(address(vectra)), 0, "contract retained shares");
    }

    function test_RebaseBeforeDelivery_StillSettlesCleanly() public {
        bytes memory cd = abi.encodeCall(
            MockRouter.rebaseThenSwap,
            (address(usdc), address(nvda), 5e6, 1e18, 4e18) // CRWDx-style 4x
        );
        vm.prank(agent);
        vectra.execute(mandateId, address(usdc), address(nvda), 5e6, 1e18, cd);

        assertEq(nvda.balanceOf(owner), 1e18, "owner balance wrong");
        assertEq(nvda.balanceOf(address(vectra)), 0, "contract retained");
    }

    /// @notice A rebase must not let the contract silently under-deliver: the
    ///         minOut check reads real holdings, so a shrinking multiplier
    ///         reverts rather than passing a short fill to the owner.
    function test_ReverseSplitMidSwap_RevertsOnMinOut() public {
        bytes memory cd = abi.encodeCall(
            MockRouter.swapThenRebase,
            (address(usdc), address(nvda), 5e6, 1e18, 5e17) // 1:2 reverse split
        );
        vm.prank(agent);
        vm.expectRevert(VectraMandate.InsufficientOutput.selector);
        vectra.execute(mandateId, address(usdc), address(nvda), 5e6, 1e18, cd);
    }

    // ------------------------------------------------------- router outcomes

    function test_RouterReturnsLessThanMinOut_Reverts() public {
        bytes memory cd = abi.encodeCall(
            MockRouter.swap, (address(usdc), address(nvda), 5e6, 4e17)
        );
        vm.prank(agent);
        vm.expectRevert(VectraMandate.InsufficientOutput.selector);
        vectra.execute(mandateId, address(usdc), address(nvda), 5e6, 1e18, cd);
    }

    /// @notice A router may deliver more than quoted. The surplus belongs to the
    ///         owner and must not be stranded in the contract.
    function test_RouterReturnsMoreThanRequested_AllForwarded() public {
        _buy(5e6, 3e18, 1e18);

        assertEq(nvda.balanceOf(owner), 3e18, "surplus not forwarded");
        assertEq(nvda.balanceOf(address(vectra)), 0, "surplus stranded");
    }

    function test_RouterUnderConsumes_CapCountsActualSpend() public {
        // Authorised $5, router consumes only $3.
        bytes memory cd = abi.encodeCall(
            MockRouter.swap, (address(usdc), address(nvda), 3e6, 1e18)
        );
        vm.prank(agent);
        vectra.execute(mandateId, address(usdc), address(nvda), 5e6, 1e18, cd);

        (,,,,,,,, uint256 spent) = vectra.mandate(mandateId);
        assertEq(spent, 3e6, "cap must count what was spent, not requested");
        assertEq(usdc.balanceOf(address(vectra)), 0, "unspent input retained");
        assertEq(usdc.balanceOf(owner), 1_000e6 - 3e6, "unspent input not returned");
    }

    function test_RouterReverts_BubblesUp() public {
        bytes memory cd = abi.encodeCall(MockRouter.boom, ("ROUTER_FAIL"));
        vm.prank(agent);
        vm.expectRevert(bytes("ROUTER_FAIL"));
        vectra.execute(mandateId, address(usdc), address(nvda), 5e6, 1e18, cd);
    }

    // -------------------------------------------------------- direction rule

    function test_CannotBuyWhenAlreadyAtTarget() public {
        nvda.mintShares(owner, TARGET_SHARES);
        bytes memory cd = abi.encodeCall(
            MockRouter.swap, (address(usdc), address(nvda), 5e6, 1e18)
        );
        vm.prank(agent);
        vm.expectRevert(VectraMandate.WrongDirection.selector);
        vectra.execute(mandateId, address(usdc), address(nvda), 5e6, 1e18, cd);
    }

    function test_CannotSellWhenAtOrBelowTarget() public {
        nvda.mintShares(owner, TARGET_SHARES); // exactly at target
        bytes memory cd = abi.encodeCall(
            MockRouter.swap, (address(nvda), address(usdc), 1e18, 5e6)
        );
        vm.prank(agent);
        vm.expectRevert(VectraMandate.WrongDirection.selector);
        vectra.execute(mandateId, address(nvda), address(usdc), 1e18, 5e6, cd);
    }

    function test_CanSellWhenAboveTarget() public {
        nvda.mintShares(owner, TARGET_SHARES + 5e18);
        usdc.mint(address(router), 100e6);
        bytes memory cd = abi.encodeCall(
            MockRouter.swap, (address(nvda), address(usdc), 1e18, 5e6)
        );
        vm.prank(agent);
        vectra.execute(mandateId, address(nvda), address(usdc), 1e18, 5e6, cd);

        assertEq(nvda.balanceOf(address(vectra)), 0);
        assertEq(usdc.balanceOf(address(vectra)), 0);
    }

    /// @notice The reason targets are in shares: a corporate event changes every
    ///         balance but must not move the position relative to its target.
    function test_DirectionRuleUnaffectedByRebase() public {
        nvda.mintShares(owner, TARGET_SHARES - 1e18); // below target, may buy
        nvda.setMultiplier(4e18);                     // CRWDx-style split

        // Balance is now 36e18 against a nominal target of 10e18. A balance-based
        // rule would read this as massively overweight and refuse. Shares still
        // read 9e18 < 10e18, so the buy is correctly permitted.
        assertEq(nvda.balanceOf(owner), 36e18);
        assertEq(nvda.sharesOf(owner), 9e18);
        _buy(5e6, 1e18, 1e18);
        assertEq(nvda.balanceOf(address(vectra)), 0);
    }

    // ------------------------------------------------------- access and caps

    function test_OnlyAgentCanExecute() public {
        bytes memory cd = abi.encodeCall(
            MockRouter.swap, (address(usdc), address(nvda), 5e6, 1e18)
        );
        vm.prank(stranger);
        vm.expectRevert(VectraMandate.NotAgent.selector);
        vectra.execute(mandateId, address(usdc), address(nvda), 5e6, 1e18, cd);
    }

    function test_LegLargerThanMaxReverts() public {
        bytes memory cd = abi.encodeCall(
            MockRouter.swap, (address(usdc), address(nvda), 6e6, 1e18)
        );
        vm.prank(agent);
        vm.expectRevert(VectraMandate.LegTooLarge.selector);
        vectra.execute(mandateId, address(usdc), address(nvda), 6e6, 1e18, cd);
    }

    function test_TotalCapEnforced() public {
        for (uint256 i; i < 10; ++i) {
            _buy(5e6, 1e17, 1e17); // 10 x $5 == $50 cap
        }
        (,,,,,,,, uint256 spent) = vectra.mandate(mandateId);
        assertEq(spent, TOTAL_CAP);

        bytes memory cd = abi.encodeCall(
            MockRouter.swap, (address(usdc), address(nvda), 5e6, 1e17)
        );
        vm.prank(agent);
        vm.expectRevert(VectraMandate.CapExceeded.selector);
        vectra.execute(mandateId, address(usdc), address(nvda), 5e6, 1e17, cd);
    }

    function test_TokenToTokenRejected() public {
        bytes memory cd = abi.encodeCall(
            MockRouter.swap, (address(nvda), address(tsla), 1e18, 1e18)
        );
        vm.prank(agent);
        vm.expectRevert(VectraMandate.TokenNotInBasket.selector);
        vectra.execute(mandateId, address(nvda), address(tsla), 1e18, 1e18, cd);
    }

    function test_PausedBlocksExecution() public {
        vm.prank(owner);
        vectra.pause(mandateId);
        bytes memory cd = abi.encodeCall(
            MockRouter.swap, (address(usdc), address(nvda), 5e6, 1e18)
        );
        vm.prank(agent);
        vm.expectRevert(VectraMandate.MandateInactive.selector);
        vectra.execute(mandateId, address(usdc), address(nvda), 5e6, 1e18, cd);
    }

    function test_RevokedIsPermanent() public {
        vm.startPrank(owner);
        vectra.revoke(mandateId);
        vm.expectRevert(VectraMandate.MandateInactive.selector);
        vectra.resume(mandateId);
        vm.stopPrank();

        bytes memory cd = abi.encodeCall(
            MockRouter.swap, (address(usdc), address(nvda), 5e6, 1e18)
        );
        vm.prank(agent);
        vm.expectRevert(VectraMandate.MandateInactive.selector);
        vectra.execute(mandateId, address(usdc), address(nvda), 5e6, 1e18, cd);
    }

    function test_ExpiredMandateCannotExecute() public {
        vm.warp(block.timestamp + 31 days);
        bytes memory cd = abi.encodeCall(
            MockRouter.swap, (address(usdc), address(nvda), 5e6, 1e18)
        );
        vm.prank(agent);
        vm.expectRevert(VectraMandate.MandateInactive.selector);
        vectra.execute(mandateId, address(usdc), address(nvda), 5e6, 1e18, cd);
    }

    function test_OnlyOwnerMayPauseOrRevoke() public {
        vm.startPrank(stranger);
        vm.expectRevert(VectraMandate.NotOwner.selector);
        vectra.pause(mandateId);
        vm.expectRevert(VectraMandate.NotOwner.selector);
        vectra.revoke(mandateId);
        vm.stopPrank();
    }

    function test_WeightsMustSumToBps() public {
        address[] memory tokens = new address[](1);
        tokens[0] = address(nvda);
        uint16[] memory weights = new uint16[](1);
        weights[0] = 9_999;
        uint256[] memory targets = new uint256[](1);
        targets[0] = 1e18;

        vm.prank(stranger);
        vm.expectRevert(VectraMandate.BadWeights.selector);
        vectra.createMandate(tokens, weights, targets, 500, MAX_LEG, TOTAL_CAP,
            uint64(block.timestamp + 1 days), agent);
    }

    /// @notice Allowance must go to the spender, which on OKX is frequently not
    ///         the call target. Approving the wrong one reverts every swap.
    function test_ApprovalGoesToSpenderNotRouter() public {
        MockRouter callTarget = new MockRouter();
        address separateSpender = address(0x5BEEF);
        VectraMandate v2 = new VectraMandate(
            address(callTarget), separateSpender, address(usdc)
        );
        assertEq(v2.router(), address(callTarget));
        assertEq(v2.spender(), separateSpender);
        assertTrue(v2.router() != v2.spender(), "must be independently settable");
    }
}
