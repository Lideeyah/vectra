// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import {Test} from "forge-std/Test.sol";

/**
 * @notice Deploys the DEPLOYMENT artifact inside a fork running a newer EVM.
 *
 * The VM's EVM version and the contract's compilation target are independent.
 * The fork must run Cancun because the chain it forks runs Uniswap V4, which
 * needs transient storage — but the contract under test does not have to be
 * recompiled for Cancun to live on it.
 *
 * So the creation bytecode is read from the paris artifact in ./out, deployed
 * with CREATE, and the resulting runtime code is byte-for-byte what a mainnet
 * deployment produces. Fork tests then exercise the exact deployed bytecode
 * rather than a recompilation that has to be argued equivalent.
 *
 * Build the artifact first with the default profile:  forge build
 */
abstract contract ParisArtifact is Test {
    string constant ARTIFACT = "out/VectraMandate.sol/VectraMandate.json";

    /// @dev Deploys from the paris creation code as `deployer` at its current
    ///      nonce, so the address matches a real deployment's CREATE address.
    function deployParisArtifact(
        address deployer,
        uint64 nonce,
        address router,
        address spender,
        address usdc
    ) internal returns (address deployed) {
        bytes memory creation = vm.parseJsonBytes(vm.readFile(ARTIFACT), ".bytecode.object");
        bytes memory initcode = abi.encodePacked(
            creation, abi.encode(router, spender, usdc)
        );

        vm.setNonce(deployer, nonce);
        vm.prank(deployer);
        assembly {
            deployed := create(0, add(initcode, 0x20), mload(initcode))
        }
        require(deployed != address(0), "paris artifact deployment failed");

        // Self-verifying: the runtime placed on chain must be the same length as
        // the artifact's, which a cancun recompile would not be — that build is
        // 10,436 bytes against paris's 10,641. Length alone is weak, so the
        // caller also asserts the full hash; this catches the common case
        // immediately and with a readable message.
        bytes memory expectedRuntime =
            vm.parseJsonBytes(vm.readFile(ARTIFACT), ".deployedBytecode.object");
        assertEq(deployed.code.length, expectedRuntime.length,
            "deployed runtime is not the deployment artifact (wrong profile?)");
    }

    /// @dev The claim, made checkable. Hash the runtime code actually present at
    ///      the address and compare it against the recorded deployment hash, so
    ///      the test fails loudly if the artifact ever drifts from what was
    ///      verified. Pass bytes32(0) to print the hash instead of asserting.
    function assertDeployedHash(address deployed, bytes32 expected) internal {
        bytes32 actual = keccak256(deployed.code);
        if (expected == bytes32(0)) {
            emit log_named_bytes32("deployed runtime keccak", actual);
            emit log_named_uint("deployed runtime bytes", deployed.code.length);
            return;
        }
        assertEq(actual, expected,
            "code at the test address is NOT the recorded deployment artifact");
    }
}
