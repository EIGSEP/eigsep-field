#!/usr/bin/env bash
# Fetch a tagged eigsep-field image from GitHub Releases, reassemble its
# split parts, verify sha256, decompress, and print the dd command to flash.
# The dd is intentionally NOT executed here -- review and run it yourself
# against the correct /dev/sdX.
#
#   ./scripts/flash-image.sh <tag> [dest-dir]
#
#   <tag>      Release tag, e.g. v2026-5.0-rc1
#   [dest-dir] Where to drop the image. Defaults to ./out.
#
# Sibling of download-image.sh: that one reads the blessed [image] entry
# from manifest.toml; this one is for rc cycles where the manifest has
# not yet been bumped to the rc tag.
set -euo pipefail

cd "$(dirname "$0")/.."

TAG=${1:-}
DEST=${2:-out}

if [[ -z "$TAG" ]]; then
    echo "usage: $0 <tag> [dest-dir]" >&2
    exit 2
fi

mkdir -p "$DEST"
cd "$DEST"

echo "downloading image assets for $TAG"
gh release download "$TAG" --repo EIGSEP/eigsep-field \
    --pattern '*.img.xz.part.*' --pattern '*.img.xz.sha256'

# Auto-discover the joined asset name from the parts. Pi-gen embeds the
# build date in the filename, so we cannot hard-code it. Refuse to guess
# if more than one image stem is present.
shopt -s nullglob
parts=( *.img.xz.part.* )
shopt -u nullglob
if (( ${#parts[@]} == 0 )); then
    echo "no .img.xz.part.* assets found in release $TAG" >&2
    exit 1
fi
IFS=$'\n' parts=( $(printf '%s\n' "${parts[@]}" | sort) ); unset IFS
JOINED=${parts[0]%.part.*}
for p in "${parts[@]}"; do
    if [[ "${p%.part.*}" != "$JOINED" ]]; then
        echo "multiple image stems found in release; refusing to guess" >&2
        exit 1
    fi
done

echo "concatenating ${#parts[@]} part(s) -> $JOINED"
cat "${parts[@]}" > "$JOINED"
rm "${parts[@]}"

echo "verifying sha256"
# --ignore-missing skips the now-deleted .part.* lines in the sidecar and
# verifies only the joined archive.
sha256sum -c --ignore-missing "${JOINED}.sha256"

echo "decompressing $JOINED"
xz -d --keep "$JOINED"
IMG=${JOINED%.xz}

cat <<EOF

image ready: $(pwd)/$IMG

To flash, identify the SD card device with 'lsblk' (pick the disk, not a
partition), then run:

    sudo dd if=$(pwd)/$IMG of=/dev/sdX bs=4M status=progress conv=fsync

This is destructive -- it will overwrite /dev/sdX. Double-check the device
before running.
EOF
