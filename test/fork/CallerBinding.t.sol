// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import {Test, console2} from "forge-std/Test.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {VectraMandate} from "../../contracts/VectraMandate.sol";

/**
 * @notice Does a swap payload built for one address work when forwarded by
 *         another? The contract will be the caller, not the wallet the payload
 *         was requested for, and the calldata encodes its caller.
 *
 * The payload arrives by environment variable from a fetch that happened
 * seconds earlier IN THE SAME JOB. It is deliberately never read from a file:
 * the router enforces a deadline, so a payload routed through a commit, a
 * notification and a human has four chances to expire before it is used. Every
 * earlier attempt died of exactly that.
 *
 * The contract is deployed at the PREDICTED mainnet address, so the payload is
 * built for the address the real deployment will occupy. That answers the
 * question before any gas is spent rather than after.
 *
 * Run via the caller-binding workflow, which fetches and forwards in one job.
 */
contract CallerBindingTest is Test {
    address constant ROUTER = 0x7c5bEE2a8091C3ef39072f64F18Fac913060AEaF;
    address constant SPENDER = 0x8b773D83bc66Be128c60e07E17C8901f7a64F000;
    address constant USDC = 0xB6CEceAB302E2E4948951eE7843FC24E92933061;
    address constant NVDAX = 0xc845b2894dBddd03858fd2D643B4eF725fE0849d;

    /// @dev Frozen at nonce 0 until the deploy; see SPEC 14A.
    address constant DEPLOYER = 0x2F45E637920Cc7C7BE15130ab49224C989572AD8;

    VectraMandate internal vectra;
    address internal owner = address(0xBEEF11);
    address internal agent = address(0xA6E27);
    bytes internal payload;
    uint256 internal amountIn;
    uint256 internal minOut;

    function setUp() public {
        payload = vm.envBytes("VECTRA_PAYLOAD");
        amountIn = vm.envOr("VECTRA_PAYLOAD_AMOUNTIN", uint256(5e6));
        minOut = vm.envOr("VECTRA_PAYLOAD_MINOUT", uint256(1));

        // Deploy at the predicted mainnet address by deploying AS the deployer
        // at the nonce the prediction assumed.
        vm.setNonce(DEPLOYER, 0);
        vm.prank(DEPLOYER);
        vectra = new VectraMandate(ROUTER, SPENDER, USDC);
        console2.log("contract deployed in-fork at", address(vectra));
    }

    function _none() internal pure returns (address[] memory a) { a = new address[](0); }

    function test_PayloadBuiltForTheContractIsForwardable() public {
        // The payload must have been built for this exact address, or the test
        // answers nothing.
        address builtFor = vm.envAddress("VECTRA_PAYLOAD_WALLET");
        assertEq(builtFor, address(vectra),
            "payload was built for a different address than the one deployed");

        address to = vm.envOr("VECTRA_PAYLOAD_TO", ROUTER);
        assertEq(to, ROUTER, "payload targets an unexpected router");

        // Align the fork's clock with the wall time the payload was issued at.
        // A fork pinned to a past block has that block's timestamp, which can
        // be behind the router's deadline, and an expiry revert would then be a
        // property of the test rather than of the router.
        uint256 fetchedAt = vm.envOr("VECTRA_FETCH_TIME", uint256(0));
        if (fetchedAt > block.timestamp) {
            console2.log("warping fork clock from", block.timestamp);
            console2.log("                     to", fetchedAt);
            vm.warp(fetchedAt);
        } else {
            console2.log("fork clock already at or ahead of fetch time", block.timestamp);
        }

        deal(USDC, owner, 1_000e6);

        address[] memory tokens = new address[](1);
        tokens[0] = NVDAX;
        uint16[] memory w = new uint16[](1);
        w[0] = 10_000;
        uint256[] memory t = new uint256[](1);
        t[0] = 1_000e18;

        vm.startPrank(owner);
        IERC20(USDC).approve(address(vectra), type(uint256).max);
        uint256 id = vectra.createMandate(VectraMandate.MandateParams({
            tokens: tokens, weightsBps: w, targetShares: t, driftBps: 500,
            maxLegUsdc: 5e6, totalCapUsdc: 50e6, maxLegBpsOfTarget: 2_000,
            expiry: uint64(block.timestamp + 30 days), agent: agent
        }));
        vm.stopPrank();

        uint256 before = IERC20(NVDAX).balanceOf(owner);
        console2.log("forwarding a payload built seconds ago, minOut", minOut);

        vm.prank(agent);
        vectra.execute(id, USDC, NVDAX, amountIn, 1, payload, _none());

        uint256 received = IERC20(NVDAX).balanceOf(owner) - before;
        console2.log("NVDAx delivered to the mandate owner", received);
        assertGt(received, 0, "no output reached the owner");

        // Whatever the router did, the contract keeps nothing.
        assertLe(IERC20(USDC).balanceOf(address(vectra)), vectra.DUST_WEI());
        assertLe(IERC20(NVDAX).balanceOf(address(vectra)), vectra.DUST_WEI());

        console2.log("CALLER BINDING: a payload built for the contract works "
                     "when the contract forwards it");
    }
}
