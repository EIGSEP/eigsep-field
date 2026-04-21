#!/usr/bin/env bash
# Fetch the tagged EIGSEP field image from GitHub Releases and verify sha256.
#
#   ./scripts/download-image.sh [tag] [dest-dir]
#
# Image assets are split into <=1800M parts named <asset>.part.aa, .ab, ...
# This script downloads all parts, concatenates, and verifies.
set -euo pipefail

cd "$(dirname "$0")/.."

TAG=${1:-}
DEST=${2:-.}

if [[ -z "$TAG" ]]; then
    TAG=$(python3 -c "import tomllib; print(tomllib.load(open('manifest.toml','rb'))['image']['tag'])")
fi
ASSET=$(python3 -c "import tomllib; print(tomllib.load(open('manifest.toml','rb'))['image']['asset'])")

mkdir -p "$DEST"
cd "$DEST"

echo "downloading all assets for $TAG into $(pwd)"
gh release download "$TAG" --repo EIGSEP/eigsep-field --pattern "${ASSET}*"

# Reassemble split parts if present.
if ls "${ASSET}".part.* >/dev/null 2>&1; then
    echo "concatenating split parts"
    cat "${ASSET}".part.* > "$ASSET"
    rm "${ASSET}".part.*
fi

if [[ -f "${ASSET}.sha256" ]]; then
    echo "verifying sha256"
    sha256sum -c "${ASSET}.sha256"
else
    echo "warning: no ${ASSET}.sha256 sidecar; skipping integrity check" >&2
fi

echo "image ready: $(pwd)/$ASSET"
