#!/bin/bash
# Local preflight: replays every patch/test step of .github/workflows/triview-b1.yml on Linux
# (no shader compile, no MSVC, no private UESDK). Run it on the exact commit you will push.
# Usage: preflight.sh <path-to-UEVR-Quad-Views-Mono-checkout> [cache-dir]
set -e
REPO=$(realpath "$1"); CACHE=$(realpath -m "${2:-$HOME/.duoview-preflight}"); HERE=$(dirname "$(realpath "$0")")
mkdir -p "$CACHE/shim" && cd "$CACHE"
[ -d joey ] || { git clone -q https://github.com/joeyhodge/UEVR joey && git -C joey checkout -q 5ac7edc207866569334175e4ed8a7517971547f6; }
[ -d frontend ] || { git clone -q https://github.com/joeyhodge/uevr-frontend frontend && git -C frontend checkout -q 60be4b0f9a646109fd9fdf448bacd41477234091; }
cp "$HERE/fxc_stub.py" shim/fxc && chmod +x shim/fxc
git -C frontend checkout -q -- . && git -C frontend clean -qfd
rm -rf backend workspace && cp -r joey backend && git clone -q "$REPO" workspace && git -C workspace checkout -q "$(git -C "$REPO" rev-parse HEAD)"
export PYTHONDONTWRITEBYTECODE=1 PATH="$CACHE/shim:$PATH"
python3 "$HERE/replay.py" workspace/.github/workflows/triview-b1.yml workspace backend frontend | grep -v "^SKIP(sdk)"
echo "Generated sources: $CACHE/backend/src/mods  shaders: $CACHE/workspace/duoview"
