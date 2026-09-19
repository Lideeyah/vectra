// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import {Test, console2} from "forge-std/Test.sol";

/**
 * @notice Proves the profile split is real rather than decorative.
 *
 * A profile that silently did nothing would look identical to one that worked —
 * the failure this repository keeps finding — so the split is asserted from both
 * sides instead of assumed.
 *
 * The discriminator is raw bytecode rather than Solidity, because solc refuses
 * to COMPILE tstore under a paris evm_version, which would break the deployment
 * build rather than testing it. Etched runtime code sidesteps the compiler and
 * tests the EVM itself:
 *
 *   602a  PUSH1 42      6000 PUSH1 0    5d TSTORE
 *   6000  PUSH1 0       5c   TLOAD
 *   600052 MSTORE       6020 PUSH1 32   6000 PUSH1 0   f3 RETURN
 *
 * Under Cancun it returns 42. Under Paris, TSTORE is not activated and the call
 * fails outright.
 */
contract EvmProfileTest is Test {
    address constant PROBE = address(0x7541);

    function test_Fork_TransientStorageAvailability() public {
        vm.etch(PROBE, hex"602a60005d60005c60005260206000f3");

        (bool ok, bytes memory ret) = PROBE.call("");
        uint256 value = (ok && ret.length == 32) ? abi.decode(ret, (uint256)) : 0;

        console2.log("tstore/tload call succeeded:", ok);
        console2.log("value read back:", value);

        if (vm.envOr("VECTRA_EXPECT_CANCUN", false)) {
            assertTrue(ok, "TSTORE not activated: running under the wrong profile");
            assertEq(value, 42, "transient storage did not round-trip");
            console2.log("PASS: transient storage active, Cancun profile in force");
        } else {
            assertFalse(ok, "TSTORE IS activated: expected the paris profile");
            console2.log("PASS: transient storage inactive, Paris profile in force");
        }
    }
}
