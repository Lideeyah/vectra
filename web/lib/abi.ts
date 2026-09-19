/**
 * The contract ABI, generated from the compiled artifact rather than written by
 * hand.
 *
 * A hand-written copy had `expiry` and `maxLegBpsOfTarget` transposed in the
 * MandateParams tuple. That changes the createMandate selector, so every call
 * hit no function at all and reverted with empty data — 28,470 gas, no error
 * name, nothing to decode.
 *
 * Nothing could catch it. Solidity initialises structs BY NAME, which is
 * order-independent, so the contract tests and the seed script were all correct
 * and all passed while this file was wrong. Only a positional caller — this one
 * — could see it, and only against a real chain.
 *
 * Regenerate with:  node scripts/gen-abi.mjs
 * Check for drift:  node scripts/gen-abi.mjs --check
 */
export { VECTRA_ABI } from "./abi.generated";
