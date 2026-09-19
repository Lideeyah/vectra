// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import {Script, console2} from "forge-std/Script.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {VectraMandate} from "../contracts/VectraMandate.sol";

interface IXStock is IERC20 {
    function sharesOf(address) external view returns (uint256);
}

/**
 * Executes a REAL leg against the REAL router on an anvil fork of X Layer, so
 * the interface can be built against genuine Executed logs before a mainnet
 * mandate is funded.
 *
 * A SELL is used deliberately: the owner already holds the rebasing token, so
 * no test account needs to be given stablecoins. The leg is NVDAx into USDC.
 *
 * This is development data. It does not ship. But the events it produces have
 * exactly the shape mainnet will produce, so the rendering code it exercises is
 * the code that will render mainnet events unchanged.
 */
contract DevLeg is Script {
    address constant ROUTER = 0x7c5bEE2a8091C3ef39072f64F18Fac913060AEaF;
    address constant SPENDER = 0x8b773D83bc66Be128c60e07E17C8901f7a64F000;
    address constant USDC = 0xB6CEceAB302E2E4948951eE7843FC24E92933061;
    address constant NVDAX = 0xc845b2894dBddd03858fd2D643B4eF725fE0849d;
    address constant WNVDAX = 0xa8ddb5Cd96b5222AFe198316E9A57CAA642850D5;

    uint256 constant OWNER_KEY =
        0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80;
    uint256 constant AGENT_KEY =
        0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d;

    function owner() internal pure returns (address) { return vm.addr(OWNER_KEY); }
    function agent() internal pure returns (address) { return vm.addr(AGENT_KEY); }

    /// Step 1: deploy and seed, printing the address the payload must be built for.
    function setup() external {
        vm.startBroadcast(OWNER_KEY);
        VectraMandate vectra = new VectraMandate(ROUTER, SPENDER, USDC);
        vm.stopBroadcast();

        // The tokens are moved OUTSIDE this script, by cast with
        // anvil_impersonateAccount. vm.startBroadcast on an arbitrary address
        // with --unlocked does not produce a signer, which is the failure this
        // exact pattern already produced once during local seeding.
        uint256 held = IXStock(NVDAX).sharesOf(owner());
        require(held > 0, "owner holds no NVDAx: run the impersonated transfer first");

        address[] memory tokens = new address[](1);
        tokens[0] = NVDAX;
        uint16[] memory w = new uint16[](1);
        w[0] = 10_000;
        uint256[] memory targets = new uint256[](1);
        targets[0] = held / 2;                 // well above target, so a SELL is admissible

        vm.startBroadcast(OWNER_KEY);
        IERC20(NVDAX).approve(address(vectra), type(uint256).max);
        uint256 id = vectra.createMandate(VectraMandate.MandateParams({
            tokens: tokens, weightsBps: w, targetShares: targets,
            driftBps: 500, maxLegUsdc: 5e6, totalCapUsdc: 50e6,
            expiry: uint64(block.timestamp + 30 days),
            maxLegBpsOfTarget: 5000, agent: agent()
        }));
        vm.stopBroadcast();

        console2.log("VECTRA", address(vectra));
        console2.log("MANDATE", id);
        console2.log("OWNER", owner());
        console2.log("AGENT", agent());
        console2.log("SHARES_HELD", held);
        console2.log("TARGET", targets[0]);
    }

    /// Step 2: forward the freshly fetched payload as the agent.
    function leg() external {
        address vectra = vm.envAddress("VECTRA");
        uint256 id = vm.envUint("MANDATE");
        uint256 amountIn = vm.envUint("AMOUNT_IN");
        bytes memory payload = vm.envBytes("VECTRA_PAYLOAD");
        uint256 minOut = vm.envUint("MIN_OUT");

        uint256 usdcBefore = IERC20(USDC).balanceOf(owner());
        console2.log("owner USDC before", usdcBefore);
        console2.log("owner shares before", IXStock(NVDAX).sharesOf(owner()));

        vm.startBroadcast(AGENT_KEY);
        VectraMandate(vectra).execute(
            id, NVDAX, USDC, amountIn, minOut, payload, new address[](0)
        );
        vm.stopBroadcast();

        console2.log("owner USDC after", IERC20(USDC).balanceOf(owner()));
        console2.log("owner shares after", IXStock(NVDAX).sharesOf(owner()));
        console2.log("USDC gained", IERC20(USDC).balanceOf(owner()) - usdcBefore);
    }
}
