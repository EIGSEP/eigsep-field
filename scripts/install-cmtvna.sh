#!/usr/bin/env bash
# Stage the CMT R60 VNA proprietary binary at [external.cmtvna].install_path.
# Operator runs this once per panda Pi after first boot:
#
#   sudo install-cmtvna.sh                      # curl from manifest URL
#   sudo install-cmtvna.sh /tmp/cmtvna-...zip   # use a pre-downloaded zip
#   install-cmtvna.sh --check                   # report presence; no install
#
# The local-file form is the expected operator path. The field image
# ships WiFi disabled and the panda Pi's only network is the eigsep LAN
# (no NAT through the backend), so download the zip on a laptop and
# `scp` it to the Pi. URL-fetch is the convenience fallback for Pis that
# happen to have internet (lab bench with a routed switch, WiFi
# manually enabled, etc.).
#
# CMT's binary is proprietary; we cannot redistribute it under
# eigsep-field's MIT license. A broken vendor URL surfaces as a clear
# script failure here and as a "missing" entry in `eigsep-field doctor`.
set -euo pipefail

ROOT=${EIGSEP_ROOT:-/opt/eigsep}
MANIFEST=${EIGSEP_MANIFEST:-${ROOT}/src/eigsep-field/manifest.toml}
ROLE_CONF=${EIGSEP_ROLE_CONF:-/boot/firmware/eigsep-role.conf}
USER_NAME=${EIGSEP_USER:-eigsep}

usage() {
    sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//'
    exit "${1:-2}"
}

read_manifest_field() {
    # Print one [external.cmtvna] field. Exits non-zero if missing.
    python3 - "$MANIFEST" "$1" <<'PY'
import sys, tomllib
manifest_path, field = sys.argv[1], sys.argv[2]
with open(manifest_path, "rb") as f:
    m = tomllib.load(f)
entry = m.get("external", {}).get("cmtvna")
if entry is None:
    sys.exit("manifest has no [external.cmtvna] entry")
val = entry.get(field, "")
if isinstance(val, list):
    print(",".join(val))
else:
    print(val)
PY
}

check_only=0
src_arg=""
for arg in "$@"; do
    case "$arg" in
        -h|--help) usage 0 ;;
        --check)   check_only=1 ;;
        -*)        echo "unknown flag: $arg" >&2; usage ;;
        *)
            if [[ -n "$src_arg" ]]; then
                echo "only one source path may be given" >&2
                usage
            fi
            src_arg="$arg"
            ;;
    esac
done

INSTALL_PATH=$(read_manifest_field install_path)
BINARY=$(read_manifest_field binary)
URL=$(read_manifest_field url)
SHA256=$(read_manifest_field sha256)
VERSION=$(read_manifest_field version)
TARGET="$INSTALL_PATH/$BINARY"

if [[ $check_only -eq 1 ]]; then
    if [[ -x "$TARGET" ]]; then
        echo "installed: $TARGET (manifest pins v$VERSION)"
        exit 0
    fi
    echo "missing: $TARGET"
    exit 1
fi

# Hard-fail on the wrong arch — the vendor URL is aarch64-specific and a
# silent install of an Intel binary would crash at service start, not here.
arch=$(uname -m)
if [[ "$arch" != "aarch64" ]]; then
    echo "host arch $arch is not aarch64; refusing install" >&2
    exit 2
fi

# Skip on non-panda Pis. The manifest's roles list is the source of
# truth; if it grows beyond panda this check still respects it.
roles=$(read_manifest_field roles)
if [[ -r "$ROLE_CONF" ]]; then
    role=$(awk -F= '/^role/ {gsub(/[[:space:]"]/, "", $2); print $2; exit}' \
        "$ROLE_CONF")
    if [[ -n "$role" ]] && ! grep -qw "$role" <<<"${roles//,/ }"; then
        echo "role=$role not in cmtvna roles=[$roles]; nothing to do" >&2
        exit 0
    fi
fi

if [[ $EUID -ne 0 ]]; then
    echo "install needs root (writes to $INSTALL_PATH)" >&2
    exit 2
fi

WORK=$(mktemp -d -t cmtvna-install.XXXXXX)
trap 'rm -rf "$WORK"' EXIT

if [[ -n "$src_arg" ]]; then
    if [[ ! -r "$src_arg" ]]; then
        echo "source file not readable: $src_arg" >&2
        exit 2
    fi
    zip_path="$src_arg"
    echo "using local source: $zip_path"
else
    zip_path="$WORK/$(basename "$URL")"
    echo "fetching $URL"
    curl -fL --retry 3 --output "$zip_path" "$URL"
fi

# Optional sha256 verification. Empty in the manifest until first
# hand-validation pins it.
if [[ -n "$SHA256" ]]; then
    actual=$(sha256sum "$zip_path" | awk '{print $1}')
    if [[ "$actual" != "$SHA256" ]]; then
        echo "sha256 mismatch: expected $SHA256, got $actual" >&2
        exit 1
    fi
    echo "sha256 verified"
fi

# CMT double-wraps the asset: an outer .zip whose only useful payload is
# the inner .tar.gz that holds bin/, lib/, etc. Both layers go into the
# tmpdir; only the unpacked tree is staged.
unzip -q -o "$zip_path" -d "$WORK/unz"
inner=$(find "$WORK/unz" -maxdepth 2 -name '*.tar.gz' -print -quit)
if [[ -z "$inner" ]]; then
    echo "no .tar.gz inside $zip_path" >&2
    exit 1
fi
tar -xzf "$inner" -C "$WORK/unz"

# Find the directory containing bin/cmtvna inside the unpacked tree.
src_root=$(dirname "$(find "$WORK/unz" -path '*/bin/cmtvna' -print -quit)")
src_root=$(dirname "$src_root")
if [[ ! -x "$src_root/bin/cmtvna" ]]; then
    echo "bin/cmtvna not found in archive (looked in $WORK/unz)" >&2
    exit 1
fi

install -d -m 0755 -o "$USER_NAME" -g "$USER_NAME" "$INSTALL_PATH"
rsync -a --delete "$src_root/" "$INSTALL_PATH/"
chown -R "$USER_NAME:$USER_NAME" "$INSTALL_PATH"
chmod 0755 "$TARGET"

echo "installed $TARGET (manifest v$VERSION)"
echo "run: sudo systemctl restart cmtvna.service"
