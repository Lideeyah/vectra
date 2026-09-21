#!/usr/bin/env bash
# The demo capture. One command, one MP4, no hands.
#
#   ./scripts/capture.sh
#
# Asserts the content of every shot against the LIVE site before recording, and
# exits non-zero naming whatever is missing — a capture that films an empty
# panel is worse than no capture.
#
# Output: data/demo/vectra-demo.mp4
set -euo pipefail
cd "$(dirname "$0")/.."

command -v ffmpeg  >/dev/null || { echo "ffmpeg is required"; exit 1; }
command -v ffprobe >/dev/null || { echo "ffprobe is required"; exit 1; }
command -v forge   >/dev/null || { echo "forge is required (the cap test runs for real)"; exit 1; }

# Run from web/ so the ESM import of playwright resolves against its
# node_modules; the script itself works in repo-root paths.
cd web
exec node scripts/capture.mjs "$@"
