#!/usr/bin/env bash
# Commit and push recorded data, surviving concurrent writers.
#
# ONE implementation, called by every workflow that writes to data/. There were
# six copies of this loop and all six had the same hole:
#
#     git push && exit 0
#     git pull --rebase --autostash origin "$BRANCH" || true
#
# The `|| true` swallows a FAILED rebase. A failed rebase does not leave the
# repository where it started — it leaves it mid-rebase, where every subsequent
# git command fails. The remaining retries then spin against a jammed tree and
# the job reports a push problem when the actual state is a conflict nobody
# resolved. In the recorder, which stays alive for 170 minutes, that silently
# cost hours of a series that cannot be backfilled.
#
# Usage:  scripts/commit_data.sh "<commit message>" [path ...]
set -uo pipefail

MSG="${1:?commit message required}"
shift
PATHS=("${@:-data}")
BRANCH="${GITHUB_REF_NAME:-$(git rev-parse --abbrev-ref HEAD)}"
ATTEMPTS=4

# A tree left mid-rebase by an earlier step fails everything below, so it is
# cleared before starting rather than inherited.
clear_rebase() {
  local d
  for d in rebase-merge rebase-apply; do
    if [ -d "$(git rev-parse --git-path $d)" ]; then
      echo "  repository was mid-rebase; aborting that first"
      git rebase --abort 2>/dev/null || true
    fi
  done
}

clear_rebase

git config user.name "Lydia Solomon"
git config user.email "lydiasolomon137@gmail.com"

# Off GitHub Actions there is no automatic GITHUB_TOKEN, so a host running the
# keeper as a plain process can commit and then fail to push for the whole life
# of the service. That failure is silent in exactly the way this script exists
# to prevent, so the credential is wired explicitly when one is supplied.
#
# The token is written into the remote URL for THIS invocation only, never into
# the repository config and never echoed. `git remote set-url` would persist it
# in .git/config where a later `git remote -v` would print it.
if [ -n "${VECTRA_GIT_TOKEN:-}" ] && [ -z "${GITHUB_ACTIONS:-}" ]; then
  ORIGIN="$(git remote get-url origin)"
  SLUG="${ORIGIN#*github.com[:/]}"
  SLUG="${SLUG%.git}"
  PUSH_URL="https://x-access-token:${VECTRA_GIT_TOKEN}@github.com/${SLUG}.git"
  echo "  pushing with VECTRA_GIT_TOKEN to ${SLUG}"
else
  PUSH_URL=""
fi

# Every push and pull below goes through these, so the token appears in one
# place rather than five.
do_push() { if [ -n "$PUSH_URL" ]; then git push -q "$PUSH_URL" "HEAD:$BRANCH"; else git push -q; fi; }
do_pull() { if [ -n "$PUSH_URL" ]; then git pull --rebase --autostash -q "$PUSH_URL" "$BRANCH"; else git pull --rebase --autostash -q origin "$BRANCH"; fi; }

if [ -z "$(git status --porcelain -- "${PATHS[@]}")" ]; then
  echo "nothing to commit in ${PATHS[*]}"
  exit 0
fi

git add -- "${PATHS[@]}"
git commit -q -m "$MSG"
echo "committed: $MSG"

for i in $(seq 1 "$ATTEMPTS"); do
  if do_push; then
    echo "pushed on attempt $i"
    exit 0
  fi

  echo "  push $i/$ATTEMPTS failed; rebasing onto origin/$BRANCH"
  if ! do_pull; then
    # The case the old code hid. Append-only files get a union merge from
    # .gitattributes and should not reach here; anything that does is a real
    # conflict, and leaving it mid-rebase would break every later command.
    echo "  rebase CONFLICTED — aborting so the tree stays usable" >&2
    git --no-pager diff --name-only --diff-filter=U >&2 || true
    git rebase --abort 2>/dev/null || true
  fi
  sleep $((i * 3))
done

echo "FAILED to push after $ATTEMPTS attempts. The commit exists locally and" >&2
echo "will be lost when this runner is destroyed." >&2
exit 1
