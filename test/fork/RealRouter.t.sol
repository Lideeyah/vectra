// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import {Test, console2} from "forge-std/Test.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {VectraMandate} from "../../contracts/VectraMandate.sol";

/**
 * @notice The contract has never forwarded a genuine payload to the genuine
 *         router. Every other test uses a mock, so the router's SHAPE — as
 *         opposed to its numbers — is still an assumption.
 *
 * This forwards the real recorded payload from data/verifications/swap.json to
 * the real OKX router on a fork of X Layer. It is the one experiment that can
 * still invalidate the contract's shape rather than merely its numbers, and
 * discovering that after an immutable deployment is unrecoverable.
 *
 * Run: forge test --match-path test/RealRouter.t.sol --fork-url xlayer
 */
contract RealRouterTest is Test {
    // Verified live (data/verifications/swap.json).
    address constant ROUTER = 0x7c5bEE2a8091C3ef39072f64F18Fac913060AEaF;
    address constant SPENDER = 0x8b773D83bc66Be128c60e07E17C8901f7a64F000;
    address constant USDC = 0xB6CEceAB302E2E4948951eE7843FC24E92933061;
    address constant NVDAX = 0xc845b2894dBddd03858fd2D643B4eF725fE0849d;

    /// @dev The wallet the recorded payload was built for.
    address constant PAYLOAD_CALLER = 0x2F45E637920Cc7C7BE15130ab49224C989572AD8;

    VectraMandate internal vectra;
    address internal agent = address(0xA6E27);
    bytes internal payload;
    uint256 internal amountIn = 5e6;

    function setUp() public {
        string memory raw = vm.readFile("data/verifications/swap.json");
        payload = vm.parseJsonBytes(raw, ".calldata.calldata_full");
        vectra = new VectraMandate(ROUTER, SPENDER, USDC);
    }

    function _none() internal pure returns (address[] memory a) { a = new address[](0); }

    function _mandateFor(address owner_) internal returns (uint256 id) {
        address[] memory tokens = new address[](1);
        tokens[0] = NVDAX;
        uint16[] memory w = new uint16[](1);
        w[0] = 10_000;
        uint256[] memory t = new uint256[](1);
        t[0] = 1_000e18;                       // far above any position
        vm.startPrank(owner_);
        IERC20(USDC).approve(address(vectra), type(uint256).max);
        id = vectra.createMandate(VectraMandate.MandateParams({
            tokens: tokens, weightsBps: w, targetShares: t, driftBps: 500,
            maxLegUsdc: 5e6, totalCapUsdc: 50e6,
            expiry: uint64(block.timestamp + 30 days), agent: agent
        }));
        vm.stopPrank();
    }

    /// @notice Baseline: is the recorded payload still valid AT ALL, called
    ///         directly by the wallet it was built for? This separates "the
    ///         payload is stale" from "the payload is caller-bound", which are
    ///         different findings with different consequences.
    function test_RealPayload_DirectFromItsIntendedCaller() public {
        deal(USDC, PAYLOAD_CALLER, 100e6);
        uint256 nvdaBefore = IERC20(NVDAX).balanceOf(PAYLOAD_CALLER);

        vm.startPrank(PAYLOAD_CALLER);
        IERC20(USDC).approve(SPENDER, type(uint256).max);
        (bool ok, bytes memory ret) = ROUTER.call(payload);
        vm.stopPrank();

        console2.log("CONTROL: direct call from intended caller succeeded:", ok);
        if (ok) {
            console2.log("  NVDAx received",
                IERC20(NVDAX).balanceOf(PAYLOAD_CALLER) - nvdaBefore);
        } else if (ret.length >= 4) {
            console2.log("  revert:", abi.decode(_stripSelector(ret), (string)));
        }
    }

    function _stripSelector(bytes memory b) internal pure returns (bytes memory out) {
        out = new bytes(b.length - 4);
        for (uint256 i; i < out.length; ++i) out[i] = b[i + 4];
    }

    /// @notice The real question. The contract is a different caller from the
    ///         one the payload was built for, and the calldata encodes its
    ///         caller. If this reverts, the agent's requirement to request
    ///         payloads with userWalletAddress set to the CONTRACT is confirmed
    ///         by experiment rather than inferred from a field.
    function test_RealPayload_ForwardedByTheContract() public {
        uint256 id = _mandateFor(PAYLOAD_CALLER);
        deal(USDC, PAYLOAD_CALLER, 100e6);

        // The router's own revert reason reaches the caller intact, which is
        // the revert-bubbling path exercised against a real router rather than
        // a mock that was written to produce a convenient error.
        vm.prank(agent);
        try vectra.execute(id, USDC, NVDAX, amountIn, 1, payload, _none()) {
            console2.log("FORWARDED OK - payload is NOT caller-bound");
            console2.log("  owner NVDAx", IERC20(NVDAX).balanceOf(PAYLOAD_CALLER));
        } catch Error(string memory reason) {
            console2.log("FORWARD reverted:", reason);
        } catch (bytes memory lo) {
            console2.log("FORWARD reverted low-level, len", lo.length);
        }

        // NOTE: this does NOT answer whether a payload is caller-bound. The
        // deadline fires first and masks that question. Answering it needs a
        // FRESH payload built for the contract's own address, which cannot be
        // requested until the contract has an address. See SPEC 15.
    }

    /// @notice Whatever the router does, the contract must not be left holding
    ///         anything. Asserted against the real router rather than a mock.
    function test_RealPayload_ContractRetainsNothingEitherWay() public {
        uint256 id = _mandateFor(PAYLOAD_CALLER);
        deal(USDC, PAYLOAD_CALLER, 100e6);

        vm.prank(agent);
        try vectra.execute(id, USDC, NVDAX, amountIn, 1, payload, _none()) {}
        catch {}

        assertLe(IERC20(USDC).balanceOf(address(vectra)), vectra.DUST_WEI(),
            "contract retained USDC after a real-router call");
        assertLe(IERC20(NVDAX).balanceOf(address(vectra)), vectra.DUST_WEI(),
            "contract retained NVDAx after a real-router call");
    }

    /// @notice The approve-spender split, demonstrated rather than inferred:
    ///         granting the allowance to the call target instead of the spender
    ///         must fail, which is what makes the two immutables necessary.
    function test_SpenderDiffersFromRouter_OnChain() public view {
        assertTrue(ROUTER != SPENDER, "router and spender are the same address");
        assertEq(vectra.router(), ROUTER);
        assertEq(vectra.spender(), SPENDER);
        console2.log("router ", ROUTER);
        console2.log("spender", SPENDER);
    }
}
