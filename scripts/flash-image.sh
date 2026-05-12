#!/usr/bin/env bash
# Fetch an eigsep-field image (Release asset or workflow-artifact),
# reassemble its split parts, verify sha256, decompress, and print the
# dd command to flash. The dd is intentionally NOT executed here --
# review and run it yourself against the correct /dev/sdX.
#
#   ./scripts/flash-image.sh [source] [dest-dir]
#
#   [source]   Either:
#                - a Release tag, e.g. v2026.5.0-rc1. Defaults to
#                  v{manifest.release} (the campaign-blessed image).
#                - run:<id>, e.g. run:25459197977 — pulls the
#                  eigsep-field-image artifact from a workflow run.
#                  Use this for DEV builds (workflow_dispatch / non-
#                  blessed tags) that never landed on a Release.
#   [dest-dir] Where to drop the image. Defaults to ./out.
#
# The asset filename is auto-discovered from the *.part.* files, so this
# works regardless of pi-gen's date-stamp without needing a pinned asset
# name in manifest.toml. Both source modes produce the same flat layout
# in dest-dir because image.yml uploads only `out/*.part.*` /
# `out/*.sha256` and upload-artifact strips the common `out/` prefix.
set -euo pipefail

cd "$(dirname "$0")/.."

SOURCE=${1:-}
DEST=${2:-out}

if [[ -z "$SOURCE" ]]; then
    SOURCE=$(python3 -c "import tomllib; print('v' + tomllib.load(open('manifest.toml','rb'))['release'])")
fi

mkdir -p "$DEST"
cd "$DEST"

if [[ "$SOURCE" == run:* ]]; then
    RUN_ID=${SOURCE#run:}
    echo "downloading image artifact for workflow run $RUN_ID"
    gh run download "$RUN_ID" --repo EIGSEP/eigsep-field \
        --name eigsep-field-image --dir .
else
    echo "downloading image assets for $SOURCE"
    gh release download "$SOURCE" --repo EIGSEP/eigsep-field \
        --pattern '*.img.xz.part.*' --pattern '*.img.xz.sha256'
fi

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
