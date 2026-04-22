#!/usr/bin/env bash
# Offline installer for the EIGSEP field stack. Runs on the Pi with no
# internet access. Resolves all deps from /opt/eigsep/wheels.
#
#   sudo install-field.sh           # install the stack
#   sudo install-field.sh --revert  # revert to the previous manifest
set -euo pipefail

FIELD_ROOT=${FIELD_ROOT:-/opt/eigsep}
WHEELS=${WHEELS:-$FIELD_ROOT/wheels}
VENV=${VENV:-$FIELD_ROOT/venv}
PIP="$VENV/bin/pip"

if [[ "${1-}" == "--revert" ]]; then
    prev=$(cat "$FIELD_ROOT/previous-release" 2>/dev/null || true)
    if [[ -z "$prev" ]]; then
        echo "no previous-release marker; cannot revert" >&2
        exit 2
    fi
    echo "reverting to $prev (not implemented: hook up the previous wheelhouse)"
    # Intentionally a stub. Revert requires both wheels-<prev>/ and the
    # previous manifest.toml on disk; those are staged by the image build
    # or by the next upgrade.
    exit 1
fi

if [[ ! -d "$WHEELS" ]]; then
    echo "wheelhouse not found at $WHEELS" >&2
    exit 2
fi
if [[ ! -x "$PIP" ]]; then
    python3 -m venv "$VENV"
fi

"$PIP" install --no-index \
    --find-links "$WHEELS" \
    --require-hashes \
    -r "$WHEELS/requirements.txt" \
    eigsep-field

# Hardware-only Python packages (e.g. casperfpga): installed from
# pre-built aarch64 wheels in the wheelhouse. Declared in manifest.toml
# [hardware.*]. Pi-only; CI/dev environments don't apply this step.
if [[ -f "$WHEELS/hardware-requirements.txt" ]]; then
    "$PIP" install --no-index \
        --find-links "$WHEELS" \
        --require-hashes \
        -r "$WHEELS/hardware-requirements.txt"
fi

"$VENV/bin/eigsep-field" info
echo
echo "install complete. run 'eigsep-field verify' to exercise producer contracts."
