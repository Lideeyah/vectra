#!/usr/bin/env bash
# Run the suites and exit with the REAL status.
#
# Piping forge output through `tail` makes the pipeline's exit code tail's, so a
# failing run looks successful to `&&`. That cost two false "all green" reports
# in one session — a check that cannot fail. Output goes to a file and is read
# from there; the exit code is never laundered through a pipe.
#
# Each suite runs under its own profile and cannot be run under the other by
# accident: the default profile is the deployment build at evm_version=paris,
# and the fork profile raises it to cancun because the forked chain runs V4,
# which needs transient storage.
set -euo pipefail

OUT="${TMPDIR:-/tmp}/vectra-test.log"

run() {
  local label="$1"; shift
  echo "=== $label"
  if "$@" >"$OUT" 2>&1; then
    # A suite that matched nothing exits 0 and reads as a pass. That is the
    # same "check that cannot fail" this script exists to stop, so it is an
    # error here rather than three green lines over an empty run.
    if grep -q "No tests found in project" "$OUT"; then
      echo "FAILED: matched no tests at all"
      tail -5 "$OUT"
      return 1
    fi
    tail -3 "$OUT"
  else
    local rc=$?
    echo "FAILED (exit $rc)"
    grep -E "^\[FAIL|Suite result|Error" "$OUT" | head -20 || tail -20 "$OUT"
    return $rc
  fi
}

# Prove the split is real rather than assuming it: the fork suite must FAIL
# under the deployment profile with the opcode error, and PASS under the fork
# profile. A profile that silently did nothing would look identical to one that
# worked, which is the failure this repository keeps finding.
if [[ "${1:-}" == "--prove-split" ]]; then
  echo "=== TSTORE probe under the DEFAULT profile (expect: inactive)"
  run "default/paris" env FOUNDRY_NO_MATCH_PATH= \
    forge test --match-path "test/fork/EvmProfile.t.sol" --fork-url xlayer -vv
  echo
  echo "=== TSTORE probe under the FORK profile (expect: active, returns 42)"
  run "fork/cancun" env FOUNDRY_PROFILE=fork FOUNDRY_NO_MATCH_PATH= \
    VECTRA_EXPECT_CANCUN=true \
    forge test --match-path "test/fork/EvmProfile.t.sol" --fork-url xlayer -vv
  echo
  echo "=== the SAME contract suite under both profiles (expect: identical)"
  run "suite @ paris " forge test
  run "suite @ cancun" env FOUNDRY_PROFILE=fork forge test
  exit 0
fi

run "default suites (profile: default, evm: paris)" forge test

if [[ "${1:-}" == "--fork" ]]; then
  # FOUNDRY_NO_MATCH_PATH= is required, not decorative: the fork profile
  # INHERITS no_match_path="test/fork/*" from the default profile, so without
  # clearing it the exclusion cancels the --match-path and zero tests run while
  # forge still exits 0. --prove-split clears it; this path did not, and the
  # suite reported ALL PASS over nothing.
  # EvmProfile asserts which EVM it is on and must be TOLD which to expect;
  # under this profile the answer is cancun. Without it the probe fails here
  # while being correct, which is a confusing way to be right.
  #
  # CallerBinding replays a REAL aggregator payload and needs VECTRA_PAYLOAD
  # from fetch_payload.py, which needs OKX credentials. It is skipped rather
  # than failed when that is absent, because a missing credential is not a
  # broken contract and a stranger cloning this repo has neither.
  FORK_SKIP=""
  if [[ -z "${VECTRA_PAYLOAD:-}" ]]; then
    FORK_SKIP="test/fork/CallerBinding.t.sol"
    echo "note: VECTRA_PAYLOAD unset, skipping CallerBinding (needs a live"
    echo "      payload: python3 fetch_payload.py, requires OKX credentials)"
  fi
  run "fork suites (profile: fork, evm: cancun)" \
    env FOUNDRY_PROFILE=fork FOUNDRY_NO_MATCH_PATH= VECTRA_EXPECT_CANCUN=true \
    forge test --match-path "test/fork/*" \
    ${FORK_SKIP:+--no-match-path "$FORK_SKIP"} --fork-url xlayer
fi

echo "=== python selection tests"
run "agent selection" python3 test_agent_selection.py
run "distance series " python3 test_distance_series.py
