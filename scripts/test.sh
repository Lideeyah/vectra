#!/usr/bin/env bash
# Run the suites and exit with the REAL status.
#
# Piping forge output through `tail` makes the pipeline's exit code tail's, so a
# failing run looks successful to `&&`. That cost two false "all green" reports
# in one session — a check that cannot fail. Output goes to a file and is read
# from there; the exit code is never laundered through a pipe.
set -euo pipefail

OUT="${TMPDIR:-/tmp}/vectra-test.log"

run() {
  local label="$1"; shift
  echo "=== $label"
  if "$@" >"$OUT" 2>&1; then
    tail -3 "$OUT"
  else
    local rc=$?
    echo "FAILED (exit $rc)"
    grep -E "^\[FAIL|Suite result|Error" "$OUT" | head -20 || tail -20 "$OUT"
    return $rc
  fi
}

run "default suites" forge test

if [[ "${1:-}" == "--fork" ]]; then
  run "fork suites" env FOUNDRY_NO_MATCH_PATH= \
    forge test --match-path "test/fork/*" --fork-url xlayer
fi

echo "=== python selection tests"
python3 test_agent_selection.py | tail -1
