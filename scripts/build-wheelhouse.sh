#!/usr/bin/env bash
# Build an offline wheelhouse for the blessed manifest.
#
#   ./scripts/build-wheelhouse.sh [manifest.toml] [wheels/] [platform]
#
# Default platform is taken from manifest.toml [system].platform, typically
# linux_aarch64. Produces:
#   $OUT/*.whl + *.tar.gz   (wheels / sdists)
#   $OUT/requirements.txt   (pinned with --generate-hashes)
set -euo pipefail

cd "$(dirname "$0")/.."

MANIFEST=${1:-manifest.toml}
OUT=${2:-wheels}

if ! command -v uv >/dev/null 2>&1; then
    echo "uv is required" >&2
    exit 2
fi

PY=$(python3 -c "import tomllib,sys; print(tomllib.load(open('$MANIFEST','rb'))['python'])")
PLATFORM=${3:-$(python3 -c "import tomllib; print(tomllib.load(open('$MANIFEST','rb')).get('system',{}).get('platform','linux_aarch64'))")}

echo "manifest: $MANIFEST"
echo "python:   $PY"
echo "platform: $PLATFORM"
echo "output:   $OUT"

rm -rf "$OUT"
mkdir -p "$OUT"

# 1. Compile a fully-pinned requirements.txt for the target platform.
#    pyproject.toml's [project.dependencies] is dynamically sourced from
#    manifest.toml, so uv resolves the blessed versions automatically.
uv pip compile \
    --python-version "$PY" \
    --python-platform "$PLATFORM" \
    --generate-hashes \
    --output-file "$OUT/requirements.txt" \
    pyproject.toml

# 2. Download every wheel (or sdist if no wheel is available) to $OUT.
uv pip download \
    --python-version "$PY" \
    --python-platform "$PLATFORM" \
    --require-hashes \
    --dest "$OUT" \
    -r "$OUT/requirements.txt"

# 3. Build off-PyPI hardware wheels (e.g. casperfpga) for the target arch
#    and emit a hashed hardware-requirements.txt alongside requirements.txt.
#    install-field.sh consumes both.
./scripts/build-git-wheels.sh "$MANIFEST" "$OUT" "$PLATFORM"
python3 scripts/hardware_requirements.py "$MANIFEST" "$OUT"

# 4. Sanity-check the wheelhouse contains every EIGSEP package at the
#    manifest-blessed version (catches sdist-only edge cases).
python3 scripts/check_wheelhouse.py "$MANIFEST" "$OUT"

echo
echo "wheelhouse built in $OUT ($(ls -1 "$OUT"/*.whl "$OUT"/*.tar.gz 2>/dev/null | wc -l) files)"
