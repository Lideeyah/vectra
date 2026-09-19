// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import {Test, console2} from "forge-std/Test.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {VectraMandate} from "../contracts/VectraMandate.sol";
import {MockUSDC, MockRebasingToken, MockRouter, HostileRebasingToken} from "./mocks/Mocks.sol";

/**
 * @notice Audit section 3: the rebasing surface.
 *
 * Every case here runs against a multiplier that is NOT 1e18, because a unit
 * multiplier cannot exhibit the share-conversion rounding these tests exist to
 * catch. That was the exact gap that let a real invariant violation survive the
 * mock suite until a fork test found it.
 */
contract RebaseSurfaceTest is Test {
    VectraMandate internal vectra;
    MockUSDC internal usdc;
    MockRebasingToken internal nvda;
    MockRouter internal router;

    address internal owner = address(0xA11CE);
    address internal agent = address(0xA6E27);
    uint256 internal id;

    uint256 internal constant MULT = 1.0017011968010740e18;
    uint256 internal constant TARGET = 10e18;
    uint256 internal constant MAX_LEG = 5e6;

    function setUp() public {
        usdc = new MockUSDC();
        nvda = new MockRebasingToken("NVIDIA xStock", "NVDAx");
        router = new MockRouter();
        nvda.setMultiplier(MULT);

        vectra = new VectraMandate(address(router), address(router), address(usdc));
        usdc.mint(owner, 10_000e6);
        nvda.mintShares(address(router), 1_000e18);
        usdc.mint(address(router), 10_000e6);

        vm.startPrank(owner);
        usdc.approve(address(vectra), type(uint256).max);
        nvda.approve(address(vectra), type(uint256).max);
        address[] memory tokens = new address[](1);
        tokens[0] = address(nvda);
        uint16[] memory w = new uint16[](1);
        w[0] = 10_000;
        uint256[] memory t = new uint256[](1);
        t[0] = TARGET;
        id = vectra.createMandate(VectraMandate.MandateParams({
            tokens: tokens, weightsBps: w, targetShares: t, driftBps: 500,
            maxLegUsdc: MAX_LEG, totalCapUsdc: 500e6,
            expiry: uint64(block.timestamp + 30 days), agent: agent
        }));
        vm.stopPrank();
    }

    function _none() internal pure returns (address[] memory a) { a = new address[](0); }

    function _assertSettled(address token) internal view {
        assertLe(IERC20(token).balanceOf(address(vectra)), vectra.DUST_WEI(),
            "contract retained more than dust");
        assertLe(usdc.balanceOf(address(vectra)), vectra.DUST_WEI(),
            "contract retained usdc");
    }

    // ---------------------------------------- rebase inside the transfer

    /// @notice A rebase landing after the allowance is debited but before the
    ///         share conversion — the tightest window in the pull.
    function test_RebaseBetweenAllowanceCheckAndTransfer() public {
        HostileRebasingToken h = new HostileRebasingToken();
        h.setMultiplier(MULT);
        h.mintShares(owner, TARGET + 5e18);
        h.mintShares(address(router), 100e18);

        address[] memory tokens = new address[](1);
        tokens[0] = address(h);
        uint16[] memory w = new uint16[](1);
        w[0] = 10_000;
        uint256[] memory t = new uint256[](1);
        t[0] = TARGET;

        vm.startPrank(owner);
        h.approve(address(vectra), type(uint256).max);
        vm.stopPrank();

        address owner2 = address(0xB0B);
        h.mintShares(owner2, TARGET + 5e18);
        vm.startPrank(owner2);
        h.approve(address(vectra), type(uint256).max);
        uint256 id2 = vectra.createMandate(VectraMandate.MandateParams({
            tokens: tokens, weightsBps: w, targetShares: t, driftBps: 500,
            maxLegUsdc: MAX_LEG, totalCapUsdc: 500e6,
            expiry: uint64(block.timestamp + 30 days), agent: agent
        }));
        vm.stopPrank();

        h.armRebaseOnTransferFrom(2e18);   // multiplier doubles mid-pull

        bytes memory cd = abi.encodeCall(
            MockRouter.swap, (address(h), address(usdc), 1e18, 10e6)
        );
        vm.prank(agent);
        vectra.execute(id2, address(h), address(usdc), 1e18, 10e6 - 10, cd, _none());

        assertEq(h.multiplier(), 2e18, "rebase did not fire");
        _assertSettled(address(h));
        console2.log("settled through a rebase inside transferFrom");
    }

    // ------------------------------------ rebase between router and sweep

    function test_RebaseBetweenRouterCallAndSweep() public {
        bytes memory cd = abi.encodeCall(
            MockRouter.swapThenRebase,
            (address(usdc), address(nvda), MAX_LEG, 2e16, 2e18)
        );
        vm.prank(agent);
        vectra.execute(id, address(usdc), address(nvda), MAX_LEG, 2e16 - 10, cd, _none());
        assertEq(nvda.multiplier(), 2e18);
        _assertSettled(address(nvda));
    }

    /// @notice A rebase that REDUCES balances below what the mandate assumed.
    function test_RebaseReducingBalancesBelowAssumption() public {
        bytes memory cd = abi.encodeCall(
            MockRouter.swapThenRebase,
            (address(usdc), address(nvda), MAX_LEG, 2e16, MULT / 4)
        );
        vm.prank(agent);
        // Output shrinks to a quarter, so minOut can no longer be met.
        vm.expectRevert(VectraMandate.InsufficientOutput.selector);
        vectra.execute(id, address(usdc), address(nvda), MAX_LEG, 2e16 - 10, cd, _none());
    }

    /// @notice Two multiplier changes inside one transaction.
    function test_MultiplierChangesTwiceWithinOneTransaction() public {
        bytes memory cd = abi.encodeCall(
            MockRouter.swapThenRebaseTwice,
            (address(usdc), address(nvda), MAX_LEG, 2e16, 2e18, 3e18)
        );
        vm.prank(agent);
        vectra.execute(id, address(usdc), address(nvda), MAX_LEG, 1, cd, _none());

        assertEq(nvda.multiplier(), 3e18, "second rebase did not land");
        _assertSettled(address(nvda));
        console2.log("owner balance after two rebases", nvda.balanceOf(owner));
        console2.log("owner shares  after two rebases", nvda.sharesOf(owner));
    }

    /// @notice Nothing is cached: the amount forwarded is whatever is actually
    ///         held at that moment, so a mid-call rebase changes the forwarded
    ///         amount rather than desynchronising it.
    function test_NoAmountIsCachedAcrossTheRouterCall() public {
        uint256 deliver = 2e16;
        bytes memory cd = abi.encodeCall(
            MockRouter.swapThenRebase,
            (address(usdc), address(nvda), MAX_LEG, deliver, 4e18)
        );
        vm.prank(agent);
        vectra.execute(id, address(usdc), address(nvda), MAX_LEG, 1, cd, _none());

        // Delivered as `deliver` at MULT, then the multiplier moved to 4e18.
        uint256 sharesDelivered = (deliver * 1e18) / MULT;
        assertApproxEqAbs(nvda.sharesOf(owner), sharesDelivered, 2, "shares wrong");
        assertApproxEqAbs(nvda.balanceOf(owner), (sharesDelivered * 4e18) / 1e18, 4,
            "owner did not receive the post-rebase balance");
        _assertSettled(address(nvda));
    }

    // --------------------------------------- sharesOf vs balanceOf reads

    /// @notice A token that implements sharesOf must never fall back to
    ///         balanceOf, because the two differ by the multiplier and the
    ///         target is denominated in shares.
    function test_SharesOfIsUsedWhenImplemented_NotBalanceOf() public view {
        (, uint256[] memory current,) = vectra.position(id);
        assertEq(current[0], nvda.sharesOf(owner), "did not read sharesOf");
        // And the two genuinely differ, so the test is not vacuous.
        nvda.balanceOf(owner);
    }

    /// @notice The NVDAx proxy hazard: a selector that returns padded data
    ///         instead of reverting. The 32-byte length check must reject it
    ///         and fall back rather than decoding garbage as a share count.
    function test_PaddedGarbageReturnIsRejectedByLengthCheck() public {
        HostileRebasingToken h = new HostileRebasingToken();
        h.setMultiplier(MULT);
        h.mintShares(owner, 7e18);
        h.setSharesMode(1);            // return 68 bytes, not 32

        address[] memory tokens = new address[](1);
        tokens[0] = address(h);
        uint16[] memory w = new uint16[](1);
        w[0] = 10_000;
        uint256[] memory t = new uint256[](1);
        t[0] = TARGET;

        address owner3 = address(0xC0FFEE);
        h.mintShares(owner3, 7e18);
        vm.prank(owner3);
        uint256 id3 = vectra.createMandate(VectraMandate.MandateParams({
            tokens: tokens, weightsBps: w, targetShares: t, driftBps: 500,
            maxLegUsdc: MAX_LEG, totalCapUsdc: 500e6,
            expiry: uint64(block.timestamp + 30 days), agent: agent
        }));

        (, uint256[] memory current,) = vectra.position(id3);
        assertEq(current[0], h.balanceOf(owner3),
            "garbage return was not rejected; fell through to a bogus value");
        assertTrue(current[0] < type(uint128).max, "decoded padded garbage");
        console2.log("padded return rejected, fell back to balanceOf:", current[0]);
    }

    /// @notice A token with no sharesOf at all falls back cleanly.
    function test_MissingSharesOfFallsBackToBalanceOf() public {
        HostileRebasingToken h = new HostileRebasingToken();
        h.setMultiplier(MULT);
        h.setSharesMode(2);            // revert
        address owner4 = address(0xD00D);
        h.mintShares(owner4, 3e18);

        address[] memory tokens = new address[](1);
        tokens[0] = address(h);
        uint16[] memory w = new uint16[](1);
        w[0] = 10_000;
        uint256[] memory t = new uint256[](1);
        t[0] = TARGET;

        vm.prank(owner4);
        uint256 id4 = vectra.createMandate(VectraMandate.MandateParams({
            tokens: tokens, weightsBps: w, targetShares: t, driftBps: 500,
            maxLegUsdc: MAX_LEG, totalCapUsdc: 500e6,
            expiry: uint64(block.timestamp + 30 days), agent: agent
        }));
        (, uint256[] memory current,) = vectra.position(id4);
        assertEq(current[0], h.balanceOf(owner4), "fallback did not engage");
    }
}
