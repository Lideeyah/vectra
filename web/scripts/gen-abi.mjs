/**
 * Generates lib/abi.generated.ts from the COMPILED artifact.
 *
 * A hand-written ABI drifted from the contract: expiry and maxLegBpsOfTarget
 * were swapped in the MandateParams tuple, which changes the function selector,
 * so every createMandate call hit no function and reverted with empty data.
 *
 * Nothing caught it because Solidity callers initialise structs BY NAME, which
 * is order-independent, while an ABI is positional. The tests and the seed
 * script were all correct and all passed while the ABI was wrong. Generating it
 * removes the class rather than the instance.
 *
 *   node scripts/gen-abi.mjs           # write
 *   node scripts/gen-abi.mjs --check   # fail if stale
 */
import { readFileSync, writeFileSync } from "node:fs";

const ART = "../../out/VectraMandate.sol/VectraMandate.json";
const OUT = "../lib/abi.generated.ts";

const artifact = JSON.parse(readFileSync(new URL(ART, import.meta.url), "utf8"));
const abi = artifact.abi;

const body = `// GENERATED from out/VectraMandate.sol/VectraMandate.json — do not edit.
// Regenerate with: node scripts/gen-abi.mjs
//
// Hand-writing this file once put expiry and maxLegBpsOfTarget in the wrong
// order, which changed the createMandate selector and made every call revert
// with empty data. Solidity struct literals are named and order-independent, so
// no test could catch it.
export const VECTRA_ABI = ${JSON.stringify(abi, null, 2)} as const;
`;

if (process.argv.includes("--check")) {
  const current = readFileSync(new URL(OUT, import.meta.url), "utf8");
  if (current !== body) {
    console.error("ABI is STALE — regenerate with: node scripts/gen-abi.mjs");
    process.exit(1);
  }
  console.log("ABI matches the compiled artifact");
} else {
  writeFileSync(new URL(OUT, import.meta.url), body);
  console.log(`wrote ${OUT} (${abi.length} entries)`);
}
