/**
 * Generate lib/bytecode.generated.ts from the compiled artifact.
 *
 * Same reason as gen-abi.mjs: a hand-copied constant is a constant that can
 * drift from the contract it claims to be, and here the consequence is
 * deploying code whose hash does not match the recorded one.
 *
 *   node scripts/gen-bytecode.mjs          write
 *   node scripts/gen-bytecode.mjs --check  fail if it has drifted
 */
import { readFileSync, writeFileSync } from "node:fs";

const artifact = JSON.parse(
  readFileSync(new URL("../../out/VectraMandate.sol/VectraMandate.json", import.meta.url)),
);
const code = artifact.bytecode.object;

const out = `/**
 * Creation bytecode for the deployment build, generated from the compiled
 * artifact — never typed or edited by hand.
 *
 * This is the paris/optimizer-200 build whose DEPLOYED runtime hashes to
 * 0xc20f87eccd8af42fa47608d1c60b4cce916df43dce508670876ab6a8c6479db9 with the
 * constructor arguments in lib/config.ts. Deploying these exact bytes from the
 * browser is what makes a wallet deploy equivalent to a forge deploy.
 *
 * Regenerate with:  node scripts/gen-bytecode.mjs
 */
export const VECTRA_CREATION_BYTECODE =
  "${code}" as \`0x\${string}\`;
`;

const target = new URL("../lib/bytecode.generated.ts", import.meta.url);

if (process.argv.includes("--check")) {
  const current = readFileSync(target, "utf8");
  if (current !== out) {
    console.error("bytecode.generated.ts has drifted from the artifact");
    process.exit(1);
  }
  console.log(`bytecode matches the artifact (${code.length / 2 - 1} bytes)`);
} else {
  writeFileSync(target, out);
  console.log(`wrote bytecode.generated.ts (${code.length / 2 - 1} bytes)`);
}
