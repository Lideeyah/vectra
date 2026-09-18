// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import {Test, console2} from "forge-std/Test.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {VectraMandate} from "../contracts/VectraMandate.sol";

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
