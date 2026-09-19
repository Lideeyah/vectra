/**
 * The fork-data gate, asserted in both directions.
 *
 * The rule is that development data must never reach the deployed build. A
 * gate that has only ever been observed excluding things is not evidence it
 * excludes the right things, so this checks that it ALSO admits mainnet data —
 * a gate stuck closed would look identical to a working one on a site that has
 * no mainnet history yet, and would then silently hide the real legs on the day
 * the mandate finally executes.
 *
 * Run:  npx tsx scripts/check-fork-gate.ts
 */
import { historyForDisplay, type History } from "../lib/data";

const base = { chainId: 196, note: "", legs: [], amendments: [] };

const fork: History = { ...base, origin: "fork" };
const mainnet: History = { ...base, origin: "mainnet" };
// Written before `origin` was recorded. Real fork data, unlabelled.
const unlabelled = { ...base } as History;

type Case = [name: string, got: History | null, want: "shown" | "hidden"];

const cases: Case[] = [
  ["fork data, flag off", historyForDisplay(fork, false), "hidden"],
  ["fork data, flag on", historyForDisplay(fork, true), "shown"],
  ["unlabelled data, flag off", historyForDisplay(unlabelled, false), "hidden"],
  ["unlabelled data, flag on", historyForDisplay(unlabelled, true), "shown"],
  // The direction that matters most on deploy day.
  ["mainnet data, flag off", historyForDisplay(mainnet, false), "shown"],
  ["mainnet data, flag on", historyForDisplay(mainnet, true), "shown"],
  ["nothing at all", historyForDisplay(null, true), "hidden"],
];

let failed = 0;
for (const [name, got, want] of cases) {
  const actual = got === null ? "hidden" : "shown";
  const ok = actual === want;
  if (!ok) failed++;
  console.log(`${ok ? "ok  " : "FAIL"}  ${name}: ${actual} (want ${want})`);
}

if (failed > 0) {
  console.error(`\n${failed} case(s) failed`);
  process.exit(1);
}
console.log(`\nall ${cases.length} cases pass`);
