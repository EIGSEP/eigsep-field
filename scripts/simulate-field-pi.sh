#!/usr/bin/env bash
# End-to-end exercise of the offline field-Pi hot-patch workflow against
# a throwaway venv + slim wheelhouse. Runs as a regular user; no /opt or
# sudo required. Intended use:
#
#   ./scripts/simulate-field-pi.sh [sibling]    # default: eigsep_observing
#
# What it does, in order:
#   1. uv venv into $TMP/venv
#   2. uv pip compile + pip download (from the seeded venv) to populate
#      $TMP/wheels from PyPI (host arch — we exercise patch/revert
#      *logic*, not cross-build)
#   3. uv build the eigsep-field meta wheel into $TMP/wheels
#   4. install everything into the venv with --no-index from the wheelhouse
#   5. git clone the chosen sibling at its manifest tag into $TMP/src
#   6. point EIGSEP_SRC / EIGSEP_WHEELS / EIGSEP_CAPTURES / VIRTUAL_ENV at
#      $TMP and run, asserting exit codes:
#         eigsep-field patch <sibling> --dry-run       (rc=0)
#         eigsep-field patch <sibling> --no-restart    (rc=0)
#         eigsep-field doctor                          (advisory: editable)
#         <make a tracked commit on the sibling>
#         eigsep-field capture <sibling>               (rc=0; .patch written)
#         eigsep-field revert <sibling> --no-restart   (rc=0)
#         eigsep-field doctor                          (no editable note)
#
# The doctor exit code itself is *not* asserted: a non-Pi host has no
# /opt/eigsep/firmware and no systemd, so doctor reports those as FAIL.
# What we assert is the editable-advisory text moving in/out of the
# output as patch/revert flips the venv install mode.
#
# Network: needs PyPI access and github.com to clone the sibling.

set -euo pipefail

cd "$(dirname "$0")/.."

SIBLING=${1:-eigsep_observing}

WORK=$(mktemp -d -t eigsep-field-sim-XXXXXX)
cleanup() { rm -rf "$WORK"; }
trap cleanup EXIT

VENV="$WORK/venv"
WHEELS="$WORK/wheels"
SRC="$WORK/src"
CAPTURES="$WORK/captures"
mkdir -p "$WHEELS" "$SRC" "$CAPTURES"

if ! command -v uv >/dev/null 2>&1; then
    echo "uv is required (see https://docs.astral.sh/uv/)" >&2
    exit 2
fi
if ! command -v git >/dev/null 2>&1; then
    echo "git is required" >&2
    exit 2
fi

# Resolve manifest fields without piping shell into Python (one read).
read -r SIBLING_TAG SIBLING_SOURCE PYTHON < <(python3 - "$SIBLING" <<'PY'
import sys, tomllib
m = tomllib.load(open("manifest.toml", "rb"))
name = sys.argv[1]
sib = m.get("packages", {}).get(name) or m.get("hardware", {}).get(name)
if not sib:
    sys.exit(f"unknown sibling {name!r}; not in [packages.*] or [hardware.*]")
print(sib["tag"], sib["source"], m["python"])
PY
)

echo "=== sibling: $SIBLING @ $SIBLING_TAG  (python $PYTHON)"
echo "=== work dir: $WORK"

echo "=== step 1: build venv (seeded with pip for wheelhouse populate)"
# `--seed` ships pip in the venv so we can use `pip download` to populate
# the wheelhouse. Older uv versions don't expose `uv pip download`; pip
# is universally available, and we drop it after the wheelhouse is built.
uv venv --seed --python "$PYTHON" "$VENV"

# uv reads UV_CONFIG_FILE if set; the patch/revert helpers default it to
# /etc/eigsep/uv.toml, which doesn't exist off-Pi. Point at a real (empty)
# file so uv doesn't error on the missing default.
UV_CONFIG="$WORK/uv.toml"
: > "$UV_CONFIG"
export UV_CONFIG_FILE="$UV_CONFIG"

# Build phase: don't enforce offline yet — we're populating the wheelhouse.
unset UV_OFFLINE UV_NO_INDEX

echo "=== step 2: compile + download requirements (PyPI)"
# pyproject.toml has dynamic deps, sourced from manifest.toml by the
# hatch hook; uv pip compile runs the build backend to discover them.
uv pip compile \
    --quiet \
    --python-version "$PYTHON" \
    --output-file "$WHEELS/requirements.txt" \
    pyproject.toml
"$VENV/bin/pip" download \
    --quiet \
    --dest "$WHEELS" \
    -r "$WHEELS/requirements.txt"

echo "=== step 3: build eigsep-field meta wheel"
uv build --wheel --quiet --out-dir "$WHEELS"

echo "=== step 4: install into venv from $WHEELS (--no-index)"
shopt -s nullglob
meta_wheels=("$WHEELS"/eigsep_field-*.whl)
shopt -u nullglob
if [[ ${#meta_wheels[@]} -eq 0 ]]; then
    echo "expected eigsep_field-*.whl in $WHEELS" >&2
    exit 1
fi
META_WHEEL="${meta_wheels[0]}"
VIRTUAL_ENV="$VENV" UV_PROJECT_ENVIRONMENT="$VENV" \
    uv pip install \
        --quiet \
        --no-index \
        --find-links "$WHEELS" \
        -r "$WHEELS/requirements.txt" \
        "$META_WHEEL"

echo "=== step 5: clone $SIBLING at $SIBLING_TAG"
git clone --quiet --depth 1 --branch "$SIBLING_TAG" \
    "$SIBLING_SOURCE" "$SRC/$SIBLING"
git -C "$SRC/$SIBLING" rev-parse HEAD > "$SRC/$SIBLING/.eigsep-blessed-commit"

echo "=== step 6: exercise patch / doctor / capture / revert"
export EIGSEP_SRC="$SRC"
export EIGSEP_WHEELS="$WHEELS"
export EIGSEP_CAPTURES="$CAPTURES"
export VIRTUAL_ENV="$VENV"
EF="$VENV/bin/eigsep-field"

assert_rc() {
    local got=$1 want=$2 msg=$3
    if [[ "$got" -ne "$want" ]]; then
        echo "FAIL: $msg (got rc=$got, want rc=$want)" >&2
        exit 1
    fi
    echo "  ok: $msg (rc=$want)"
}

set +e
"$EF" patch "$SIBLING" --dry-run
assert_rc $? 0 "patch --dry-run"

"$EF" patch "$SIBLING" --no-restart
assert_rc $? 0 "patch --no-restart"
set -e

# Doctor exit code reflects firmware/services state we can't simulate;
# verify the editable advisory line appears in its output.
DOCTOR_OUT=$("$EF" doctor 2>&1 || true)
if ! grep -q -E "note .*editable" <<<"$DOCTOR_OUT"; then
    echo "FAIL: doctor did not report editable advisory after patch" >&2
    echo "--- doctor output ---" >&2
    echo "$DOCTOR_OUT" >&2
    exit 1
fi
echo "  ok: doctor reports editable advisory after patch"

# Make a tracked-file change so capture has something to write.
SIBLING_DIR="$SRC/$SIBLING"
echo "field fix at $(date -u +%FT%TZ)" > "$SIBLING_DIR/_field_fix.txt"
git -C "$SIBLING_DIR" -c user.email=sim@example.com -c user.name=sim \
    add _field_fix.txt
git -C "$SIBLING_DIR" -c user.email=sim@example.com -c user.name=sim \
    commit --quiet -m "field fix"

set +e
"$EF" capture "$SIBLING"
assert_rc $? 0 "capture"
set -e
shopt -s nullglob
captured=("$CAPTURES"/${SIBLING}-*.patch)
shopt -u nullglob
if [[ ${#captured[@]} -eq 0 ]]; then
    echo "FAIL: capture did not write a .patch under $CAPTURES" >&2
    exit 1
fi
echo "  ok: capture wrote ${captured[0]}"

set +e
"$EF" revert "$SIBLING" --no-restart
assert_rc $? 0 "revert --no-restart"
set -e

DOCTOR_OUT=$("$EF" doctor 2>&1 || true)
if grep -q -E "note .*editable" <<<"$DOCTOR_OUT"; then
    echo "FAIL: doctor still reports editable after revert" >&2
    echo "--- doctor output ---" >&2
    echo "$DOCTOR_OUT" >&2
    exit 1
fi
echo "  ok: doctor no longer reports editable advisory after revert"

echo
echo "simulate-field-pi.sh: PASS"
