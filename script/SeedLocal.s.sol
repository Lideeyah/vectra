// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import {Script, console2} from "forge-std/Script.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {VectraMandate} from "../contracts/VectraMandate.sol";

interface IXStock is IERC20 {
    function sharesOf(address) external view returns (uint256);
    function multiplier() external view returns (uint256);
}

/**
 * Seeds a LOCAL anvil fork of X Layer so the interface can be judged against a
 * real contract holding real positions, before a mainnet mandate exists.
 *
 * Everything here is real except the chain being local: a real deployment, real
 * xStock tokens moved by their own transfer logic from a live holder, and a
 * real mandate created through the contract's own entrypoint. Nothing is
 * mocked, stubbed or seeded into the frontend.
 *
 *   anvil --fork-url https://rpc.xlayer.tech
 *   forge script script/SeedLocal.s.sol --rpc-url http://127.0.0.1:8545 --broadcast
 */
contract SeedLocal is Script {
    address constant ROUTER = 0x7c5bEE2a8091C3ef39072f64F18Fac913060AEaF;
    address constant SPENDER = 0x8b773D83bc66Be128c60e07E17C8901f7a64F000;
    address constant USDC = 0xB6CEceAB302E2E4948951eE7843FC24E92933061;

    address constant NVDAX = 0xc845b2894dBddd03858fd2D643B4eF725fE0849d;
    address constant TSLAX = 0x8aD3c73F833d3F9A523aB01476625F269aEB7Cf0;
    address constant AAPLX = 0x9d275685dC284C8eB1C79f6ABA7a63Dc75ec890a;

    /// @dev Live holders, used as the source of real tokens.
    address constant WNVDAX = 0xa8ddb5Cd96b5222AFe198316E9A57CAA642850D5;

    /// @dev anvil's first default account — the one a local wallet will hold.
    address constant OWNER = 0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266;
    address constant AGENT = 0x70997970C51812dc3A010C7d01b50e0d17dc79C8;

    /// @dev anvil default account 0. A known local key, never used elsewhere.
    uint256 constant OWNER_KEY =
        0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80;

    function run() external {
        vm.startBroadcast(OWNER_KEY);
        VectraMandate vectra = new VectraMandate(ROUTER, SPENDER, USDC);
        vm.stopBroadcast();
        console2.log("VECTRA_ADDRESS", address(vectra));

        // Real tokens, moved by the token's own transfer logic from a live
        // holder, rather than balances written into storage.
        if (IERC20(NVDAX).balanceOf(OWNER) == 0) {
            vm.startBroadcast(WNVDAX);
            IERC20(NVDAX).transfer(OWNER, 6e18);
            vm.stopBroadcast();
        }

        console2.log("owner NVDAx shares", IXStock(NVDAX).sharesOf(OWNER));
        console2.log("owner NVDAx balance", IERC20(NVDAX).balanceOf(OWNER));
        console2.log("NVDAx multiplier", IXStock(NVDAX).multiplier());

        // A basket of three, with the position deliberately OFF target so the
        // convergence view has something to show: NVDAx is held, the other two
        // are not, so one row sits above target and two sit at zero.
        address[] memory tokens = new address[](3);
        tokens[0] = NVDAX;
        tokens[1] = TSLAX;
        tokens[2] = AAPLX;

        uint16[] memory weights = new uint16[](3);
        weights[0] = 3400;
        weights[1] = 3300;
        weights[2] = 3300;

        uint256[] memory targets = new uint256[](3);
        targets[0] = 4e18;   // held ~6e18 → above target, a sell
        targets[1] = 3e18;   // held 0 → below target, a buy
        targets[2] = 2e18;   // held 0 → below target, a buy

        vm.startBroadcast(OWNER_KEY);
        IERC20(USDC).approve(address(vectra), type(uint256).max);
        uint256 id = vectra.createMandate(
            VectraMandate.MandateParams({
                tokens: tokens,
                weightsBps: weights,
                targetShares: targets,
                driftBps: 500,
                maxLegUsdc: 5e6,
                totalCapUsdc: 50e6,
                maxLegBpsOfTarget: 2000,
                expiry: uint64(block.timestamp + 30 days),
                agent: AGENT
            })
        );
        vm.stopBroadcast();

        console2.log("mandate id", id);
        (, uint256[] memory current, uint256[] memory target) = vectra.position(id);
        for (uint256 i; i < current.length; ++i) {
            console2.log("  current", current[i]);
            console2.log("  target ", target[i]);
        }
    }
}
