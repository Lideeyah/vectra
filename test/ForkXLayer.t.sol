// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import {Test, console2} from "forge-std/Test.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {IERC20Metadata} from "@openzeppelin/contracts/token/ERC20/extensions/IERC20Metadata.sol";
import {VectraMandate} from "../contracts/VectraMandate.sol";
import {MockRouter} from "./mocks/Mocks.sol";

interface IXStock is IERC20 {
    function sharesOf(address) external view returns (uint256);
    function multiplier() external view returns (uint256);
    function symbol() external view returns (string memory);
}

/**
 * @notice Fork tests against live X Layer state.
 *
 * The mock suite proves the contract behaves correctly against a model of a
 * rebasing token. This proves the model matches the real thing, and that the
 * contract reads real deployed tokens the way it assumes.
 *
 * Run with: forge test --match-path test/ForkXLayer.t.sol --fork-url xlayer
 */
contract ForkXLayerTest is Test {
    // Verified live (data/verifications/swap.json).
    address constant ROUTER = 0x7c5bEE2a8091C3ef39072f64F18Fac913060AEaF;
    address constant SPENDER = 0x8b773D83bc66Be128c60e07E17C8901f7a64F000;
    address constant USDC = 0xB6CEceAB302E2E4948951eE7843FC24E92933061;

    address constant NVDAX = 0xc845b2894dBddd03858fd2D643B4eF725fE0849d;
    address constant TSLAX = 0x8aD3c73F833d3F9A523aB01476625F269aEB7Cf0;
    address constant CRWDX = 0x214151022C2a5E380aB80CdaC31f23Ae554a7345;

    // wNVDAx, the ERC-4626 style wrapper. Holds a real NVDAx position, so it
    // serves as a live non-zero holder without needing to mint anything.
    address constant WNVDAX = 0xa8ddb5Cd96b5222AFe198316E9A57CAA642850D5;

    address internal owner = address(0xA11CE);
    address internal agent = address(0xA6E27);
    VectraMandate internal vectra;

    function setUp() public {
        vectra = new VectraMandate(ROUTER, SPENDER, USDC);
    }

    // ------------------------------------------------ real token invariants

    /// @notice The relationship the whole design rests on, checked against a
    ///         live non-zero position rather than a mock.
    function test_Fork_BalanceEqualsSharesTimesMultiplier() public view {
        IXStock t = IXStock(NVDAX);
        uint256 shares = t.sharesOf(WNVDAX);
        uint256 bal = t.balanceOf(WNVDAX);
        uint256 mult = t.multiplier();

        assertGt(shares, 0, "wrapper should hold a real position");
        console2.log("NVDAx shares   ", shares);
        console2.log("NVDAx balance  ", bal);
        console2.log("NVDAx multiplier", mult);

        // Allow one wei of rounding in either direction.
        uint256 expected = (shares * mult) / 1e18;
        assertApproxEqAbs(bal, expected, 1, "balanceOf != sharesOf * multiplier");
    }

    function test_Fork_MultipliersAreLiveAndVaried() public view {
        assertEq(IXStock(CRWDX).multiplier(), 4e18, "CRWDx should be a 4x split");
        assertGe(IXStock(NVDAX).multiplier(), 1e18, "multiplier below parity");
        assertGe(IXStock(TSLAX).multiplier(), 1e18, "multiplier below parity");
        console2.log("CRWDx multiplier", IXStock(CRWDX).multiplier());
    }

    /// @notice sharesOf must be present on every basket candidate, since the
    ///         direction rule falls back to balanceOf without it — which a
    ///         rebase would then corrupt.
    function test_Fork_SharesOfPresentOnRealTokens() public view {
        address[3] memory toks = [NVDAX, TSLAX, CRWDX];
        for (uint256 i; i < toks.length; ++i) {
            (bool ok, bytes memory ret) = toks[i].staticcall(
                abi.encodeWithSignature("sharesOf(address)", WNVDAX)
            );
            assertTrue(ok, "sharesOf reverted");
            assertEq(ret.length, 32, "sharesOf returned non-uint256");
        }
    }

    // ------------------------------------------------------- forced rebase

    /// @notice The test the design was written for: force a real corporate
    ///         event on a real deployed token and confirm shares are unmoved
    ///         while balances are not.
    function test_Fork_ForcedRebase_SharesInvariantBalanceIsNot() public {
        IXStock t = IXStock(NVDAX);
        bytes32 slot = _findMultiplierSlot(NVDAX, t.multiplier());

        uint256 sharesBefore = t.sharesOf(WNVDAX);
        uint256 balBefore = t.balanceOf(WNVDAX);

        // Simulate a 4:1 split, the CRWDx case, on NVDAx.
        vm.store(NVDAX, slot, bytes32(uint256(4e18)));
        assertEq(t.multiplier(), 4e18, "multiplier not overwritten");

        assertEq(t.sharesOf(WNVDAX), sharesBefore, "shares moved on a rebase");
        assertEq(t.balanceOf(WNVDAX), (sharesBefore * 4e18) / 1e18, "balance wrong");
        assertGt(t.balanceOf(WNVDAX), balBefore, "balance did not grow");

        console2.log("balance before split", balBefore);
        console2.log("balance after split ", t.balanceOf(WNVDAX));
        console2.log("shares unchanged    ", sharesBefore);
    }

    /// @notice The direction rule must read the same before and after a real
    ///         corporate event on a real token.
    function test_Fork_DirectionRuleSurvivesRealRebase() public {
        IXStock t = IXStock(NVDAX);
        uint256 shares = t.sharesOf(WNVDAX);
        uint256 target = shares + 1e18; // wrapper sits just below target

        _createMandate(NVDAX, target);

        (, uint256[] memory curBefore, uint256[] memory tgt) = _position();
        assertLt(curBefore[0], tgt[0], "should start below target");

        bytes32 slot = _findMultiplierSlot(NVDAX, t.multiplier());
        vm.store(NVDAX, slot, bytes32(uint256(4e18)));

        (, uint256[] memory curAfter,) = _position();
        assertEq(curAfter[0], curBefore[0], "position moved on a rebase");
        assertLt(curAfter[0], tgt[0], "still below target after a 4x split");

        // A balance-based rule would now read four times the shares and refuse.
        assertGt(t.balanceOf(WNVDAX), tgt[0], "balance exceeds target as expected");
    }

    // --------------------------------------------------- the sell side

    MockRouter internal mockRouter;
    VectraMandate internal sellVectra;

    /// @dev Called by the router MID-SWAP to force a corporate event on a real
    ///      deployed token. A mock cannot rewrite a live contract's storage, but
    ///      the test can, and cheatcodes still work when re-entered.
    function forceMultiplier(address token, uint256 value) external {
        vm.store(token, _findMultiplierSlot(token, IXStock(token).multiplier()), bytes32(value));
    }

    function _setUpSell(uint256 targetShares) internal returns (uint256 id) {
        mockRouter = new MockRouter();
        sellVectra = new VectraMandate(address(mockRouter), address(mockRouter), USDC);

        address[] memory tokens = new address[](1);
        tokens[0] = NVDAX;
        uint16[] memory weights = new uint16[](1);
        weights[0] = 10_000;
        uint256[] memory targets = new uint256[](1);
        targets[0] = targetShares;

        vm.startPrank(WNVDAX);
        IERC20(NVDAX).approve(address(sellVectra), type(uint256).max);
        id = sellVectra.createMandate(VectraMandate.MandateParams({
            tokens: tokens, weightsBps: weights, targetShares: targets,
            driftBps: 500, maxLegUsdc: 5e6, totalCapUsdc: 50e6,
            expiry: uint64(block.timestamp + 30 days), agent: agent
        }));
        vm.stopPrank();
        deal(USDC, address(mockRouter), 1_000e6);
    }

    function _none() internal pure returns (address[] memory a) {
        a = new address[](0);
    }

    /// @notice Sell with a split mid-transaction. The contract holds the
    ///         REBASING token at that moment, which is the case the buy-side
    ///         tests never exercised.
    function test_Fork_SellWithMultiplierIncrease_SettlesCleanly() public {
        uint256 shares = IXStock(NVDAX).sharesOf(WNVDAX);
        uint256 id = _setUpSell(shares / 2);          // well above target
        uint256 usdcBefore = IERC20(USDC).balanceOf(WNVDAX);

        bytes memory cd = abi.encodeCall(MockRouter.swapThenCall, (
            NVDAX, USDC, 1e18, 200e6, address(this),
            abi.encodeCall(this.forceMultiplier, (NVDAX, 2e18))
        ));
        vm.prank(agent);
        sellVectra.execute(id, NVDAX, USDC, 1e18, 200e6, cd, _none());

        assertEq(IERC20(USDC).balanceOf(WNVDAX) - usdcBefore, 200e6, "owner USDC wrong");
        assertEq(IERC20(NVDAX).balanceOf(address(sellVectra)), 0, "token retained");
        assertEq(IERC20(USDC).balanceOf(address(sellVectra)), 0, "usdc retained");
        assertEq(IXStock(NVDAX).multiplier(), 2e18, "rebase did not fire");
        console2.log("sell + split: owner received USDC", uint256(200e6));
    }

    /// @notice A short fill must revert rather than reach the owner, and the
    ///         check must read real holdings, not a computed delta.
    function test_Fork_SellWithMultiplierDecrease_ShortFillReverts() public {
        uint256 shares = IXStock(NVDAX).sharesOf(WNVDAX);
        uint256 id = _setUpSell(shares / 2);

        bytes memory cd = abi.encodeCall(MockRouter.swapThenCall, (
            NVDAX, USDC, 1e18, 150e6, address(this),                 // delivers 150
            abi.encodeCall(this.forceMultiplier, (NVDAX, 5e17))      // reverse split
        ));
        vm.prank(agent);
        vm.expectRevert(VectraMandate.InsufficientOutput.selector);
        sellVectra.execute(id, NVDAX, USDC, 1e18, 200e6, cd, _none()); // demands 200
    }

    /// @notice Under-consumed rebasing input returns to the owner, and the cap
    ///         is untouched because a sell commits no USDC.
    function test_Fork_SellUnderConsumed_ReturnsTokenAndLeavesCapAlone() public {
        uint256 shares = IXStock(NVDAX).sharesOf(WNVDAX);
        uint256 id = _setUpSell(shares / 2);
        uint256 ownerTokenBefore = IERC20(NVDAX).balanceOf(WNVDAX);

        // Authorised 2e18 of NVDAx, router consumes only 1e18.
        bytes memory cd = abi.encodeCall(
            MockRouter.swap, (NVDAX, USDC, 1e18, 200e6)
        );
        vm.prank(agent);
        sellVectra.execute(id, NVDAX, USDC, 2e18, 200e6, cd, _none());

        uint256 residual = IERC20(NVDAX).balanceOf(address(sellVectra));
        assertLe(residual, sellVectra.DUST_WEI(), "more than rounding dust retained");
        console2.log("residual wei after a rebasing-token sell", residual);
        assertApproxEqAbs(IERC20(NVDAX).balanceOf(WNVDAX), ownerTokenBefore - 1e18, 2,
            "unconsumed input not returned");

        (,,,,,,,, uint256 spent,) = sellVectra.mandate(id);
        assertEq(spent, 0, "a sell must not consume cap headroom");
        console2.log("sell under-consumed: cap spent stays", uint256(spent));
    }

    // ============================================ SECTION 2: THE UNITS TRACE

    address internal traceOwner = address(0xBEEF01);

    function _trace(string memory label, address token, address who) internal view {
        uint256 bal = IERC20(token).balanceOf(who);
        uint256 sh = IXStock(token).sharesOf(who);
        uint256 mult = IXStock(token).multiplier();
        console2.log(label);
        console2.log("    balanceOf  ", bal);
        console2.log("    sharesOf   ", sh);
        console2.log("    multiplier ", mult);
        console2.log("    shares*mult/1e18", (sh * mult) / 1e18);
    }

    /// @notice Every number at every hop for one buy, against real tokens.
    ///         An off-by-a-factor in this path is silent until catastrophic,
    ///         and every later assertion compares numbers produced by the same
    ///         conversion on both sides, so it would not surface there.
    function test_Fork_UnitsTrace_Buy() public {
        mockRouter = new MockRouter();
        VectraMandate v = new VectraMandate(address(mockRouter), address(mockRouter), USDC);

        // Real NVDAx into the router, taken from a live holder.
        vm.prank(WNVDAX);
        IERC20(NVDAX).transfer(address(mockRouter), 5e18);
        deal(USDC, traceOwner, 100e6);

        address[] memory tokens = new address[](1);
        tokens[0] = NVDAX;
        uint16[] memory w = new uint16[](1);
        w[0] = 10_000;
        uint256[] memory t = new uint256[](1);
        t[0] = 10e18;                     // target in SHARES, 18dp

        vm.startPrank(traceOwner);
        IERC20(USDC).approve(address(v), type(uint256).max);
        uint256 id = v.createMandate(VectraMandate.MandateParams({
            tokens: tokens, weightsBps: w, targetShares: t, driftBps: 500,
            maxLegUsdc: 5e6, totalCapUsdc: 50e6,
            expiry: uint64(block.timestamp + 30 days), agent: agent
        }));
        vm.stopPrank();

        uint256 amountIn = 5e6;           // $5 in USDC base units, 6dp
        uint256 deliver  = 2e16;          // 0.02 NVDAx in balance terms, 18dp

        console2.log("=== INPUT SIDE ===");
        console2.log("  USDC decimals        ", uint256(IERC20Metadata(USDC).decimals()));
        console2.log("  amountIn base units  ", amountIn);
        console2.log("  amountIn as dollars  ", amountIn / 1e6);
        console2.log("  owner USDC before    ", IERC20(USDC).balanceOf(traceOwner));
        console2.log("=== OUTPUT SIDE, BEFORE ===");
        console2.log("  NVDAx decimals       ", uint256(IERC20Metadata(NVDAX).decimals()));
        _trace("  owner NVDAx before", NVDAX, traceOwner);
        console2.log("  target (shares, 18dp)", t[0]);

        bytes memory cd = abi.encodeCall(
            MockRouter.swap, (USDC, NVDAX, amountIn, deliver)
        );
        vm.prank(agent);
        v.execute(id, USDC, NVDAX, amountIn, deliver - 10, cd, _none());

        console2.log("=== AFTER ===");
        console2.log("  owner USDC after     ", IERC20(USDC).balanceOf(traceOwner));
        console2.log("  USDC delta (6dp)     ", 100e6 - IERC20(USDC).balanceOf(traceOwner));
        _trace("  owner NVDAx after", NVDAX, traceOwner);
        (,,,,,,,, uint256 spent, uint64 ver) = v.mandate(id);
        console2.log("  cap spent (USDC 6dp) ", spent);
        console2.log("  mandate version      ", uint256(ver));
        console2.log("  contract USDC residue", IERC20(USDC).balanceOf(address(v)));
        console2.log("  contract NVDAx residue", IERC20(NVDAX).balanceOf(address(v)));

        // The conversions that must hold, asserted rather than eyeballed.
        assertEq(100e6 - IERC20(USDC).balanceOf(traceOwner), amountIn,
            "USDC moved != amountIn: a 6dp/18dp confusion");
        assertEq(spent, amountIn, "cap charged in the wrong unit");
        assertApproxEqAbs(IERC20(NVDAX).balanceOf(traceOwner), deliver, 2,
            "delivered balance wrong");
        // sharesOf * multiplier / 1e18 == balanceOf, on a live token.
        uint256 sh = IXStock(NVDAX).sharesOf(traceOwner);
        uint256 mult = IXStock(NVDAX).multiplier();
        assertApproxEqAbs((sh * mult) / 1e18, IERC20(NVDAX).balanceOf(traceOwner), 1,
            "shares/balance conversion broken");
        // The target is in SHARES; the position must be below it, not below the
        // BALANCE, which differs by the multiplier.
        assertLt(sh, t[0], "post-state compared the wrong quantity");
        assertLe(IERC20(NVDAX).balanceOf(address(v)), v.DUST_WEI());
    }

    /// @notice The same trace for a sell, where the input is the rebasing token.
    function test_Fork_UnitsTrace_Sell() public {
        uint256 id = _setUpSell(IXStock(NVDAX).sharesOf(WNVDAX) / 2);
        uint256 usdcBefore = IERC20(USDC).balanceOf(WNVDAX);
        uint256 amountIn = 1e18;   // NVDAx in BALANCE terms, 18dp
        uint256 give = 200e6;      // USDC, 6dp

        console2.log("=== SELL INPUT SIDE ===");
        console2.log("  amountIn (18dp balance)", amountIn);
        _trace("  owner NVDAx before", NVDAX, WNVDAX);
        console2.log("  owner USDC before (6dp)", usdcBefore);

        bytes memory cd = abi.encodeCall(MockRouter.swap, (NVDAX, USDC, amountIn, give));
        vm.prank(agent);
        sellVectra.execute(id, NVDAX, USDC, amountIn, give - 10, cd, _none());

        console2.log("=== AFTER ===");
        _trace("  owner NVDAx after", NVDAX, WNVDAX);
        console2.log("  owner USDC after (6dp) ", IERC20(USDC).balanceOf(WNVDAX));
        console2.log("  USDC gained (6dp)      ", IERC20(USDC).balanceOf(WNVDAX) - usdcBefore);
        (,,,,,,,, uint256 spent,) = sellVectra.mandate(id);
        console2.log("  cap spent after a sell ", spent);

        assertEq(IERC20(USDC).balanceOf(WNVDAX) - usdcBefore, give, "USDC out wrong");
        assertEq(spent, 0, "a sell charged the USDC cap");
        // The token leaving is measured in balance, and the SHARES removed are
        // balance/multiplier — not equal, and conflating them is the bug class.
        console2.log("  shares removed         ",
            (amountIn * 1e18) / IXStock(NVDAX).multiplier());
    }

    // ------------------------------------------------------------- helpers

    /// @dev Locate the storage slot backing multiplier(). xStocks are proxies
    ///      using namespaced storage, so the slot is not a small integer and is
    ///      not knowable from an ABI. Record the reads the call actually makes
    ///      and pick the one holding the value it returned.
    function _findMultiplierSlot(address token, uint256 value)
        internal
        returns (bytes32)
    {
        vm.record();
        IXStock(token).multiplier();
        (bytes32[] memory reads,) = vm.accesses(token);
        for (uint256 i; i < reads.length; ++i) {
            if (uint256(vm.load(token, reads[i])) == value) return reads[i];
        }
        revert("multiplier slot not observed among storage reads");
    }

    function _createMandate(address token, uint256 targetShares) internal {
        address[] memory tokens = new address[](1);
        tokens[0] = token;
        uint16[] memory weights = new uint16[](1);
        weights[0] = 10_000;
        uint256[] memory targets = new uint256[](1);
        targets[0] = targetShares;

        vm.prank(WNVDAX); // the live holder acts as the mandate owner
        vectra.createMandate(VectraMandate.MandateParams({
            tokens: tokens,
            weightsBps: weights,
            targetShares: targets,
            driftBps: 500,
            maxLegUsdc: 5e6,
            totalCapUsdc: 50e6,
            expiry: uint64(block.timestamp + 30 days),
            agent: agent
        }));
    }

    function _position()
        internal
        view
        returns (address[] memory, uint256[] memory, uint256[] memory)
    {
        return vectra.position(vectra.activeMandateOf(WNVDAX));
    }
}
