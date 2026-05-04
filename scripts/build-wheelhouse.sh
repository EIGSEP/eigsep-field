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

# `linux_aarch64` is our canonical platform label (used in workflow
# matrix names, image tarball filenames, and build-git-wheels.sh's
# docker target). The two cross-platform tools we drive want different
# spellings of it:
#
# - `uv pip compile` (resolve) wants uv's hyphenated manylinux tag like
#   `aarch64-manylinux_2_41` and rejects standard PEP tags outright.
# - `pip download` (fetch) wants one or more PEP 425 platform tags via
#   repeated `--platform` flags, and matches each exactly — so we have
#   to enumerate the manylinux variants we accept rather than relying
#   on a single floor. uv has no `pip download` subcommand (see
#   astral-sh/uv#3163), and `simulate-field-pi.sh` takes the same
#   approach for the same reason.
#
# `manylinux_2_41` matches Pi OS trixie (Debian 13, glibc 2.41) — the
# baseline declared in image/pi-gen-config/config. Every wheel tagged
# 2_41 or older is ABI-compatible; we list them explicitly so pip
# accepts them all, and include the legacy `manylinux2014` alias plus
# the bare `linux_<arch>` tag for completeness.
case "$PLATFORM" in
    linux_aarch64)
        UV_PLATFORM=aarch64-manylinux_2_41
        PIP_PLATFORMS=(
            linux_aarch64
            manylinux2014_aarch64
            manylinux_2_17_aarch64
            manylinux_2_28_aarch64
            manylinux_2_31_aarch64
            manylinux_2_34_aarch64
            manylinux_2_36_aarch64
            manylinux_2_38_aarch64
            manylinux_2_39_aarch64
            manylinux_2_40_aarch64
            manylinux_2_41_aarch64
        )
        ;;
    linux_x86_64)
        UV_PLATFORM=x86_64-manylinux_2_41
        PIP_PLATFORMS=(
            linux_x86_64
            manylinux2014_x86_64
            manylinux_2_17_x86_64
            manylinux_2_28_x86_64
            manylinux_2_31_x86_64
            manylinux_2_34_x86_64
            manylinux_2_36_x86_64
            manylinux_2_38_x86_64
            manylinux_2_39_x86_64
            manylinux_2_40_x86_64
            manylinux_2_41_x86_64
        )
        ;;
    *)
        UV_PLATFORM=$PLATFORM
        PIP_PLATFORMS=("$PLATFORM")
        ;;
esac

PIP_PLATFORM_ARGS=()
for p in "${PIP_PLATFORMS[@]}"; do
    PIP_PLATFORM_ARGS+=(--platform "$p")
done

echo "manifest:    $MANIFEST"
echo "python:      $PY"
echo "platform:    $PLATFORM"
echo "uv platform: $UV_PLATFORM"
echo "output:      $OUT"

rm -rf "$OUT"
mkdir -p "$OUT"

# 1. Compile a fully-pinned requirements.txt for the target platform.
#    pyproject.toml's [project.dependencies] is dynamically sourced from
#    manifest.toml, so uv resolves the blessed versions automatically.
#    --extra debug bakes the [debug.*] manifest entries (ipython,
#    matplotlib) into the wheelhouse so the field Pi has REPL + plotting
#    available offline, even though `pip install eigsep-field` (no
#    extras) doesn't pull them.
uv pip compile \
    --python-version "$PY" \
    --python-platform "$UV_PLATFORM" \
    --generate-hashes \
    --extra debug \
    --output-file "$OUT/requirements.txt" \
    pyproject.toml

# 2. Download every wheel to $OUT. We use a throwaway uv-seeded venv
#    so we always have a fresh `pip` regardless of how the caller
#    invoked the script — the README quickstart's `uv venv --python
#    3.13` doesn't seed pip, so `python3 -m pip` from inside that
#    venv would error with "No module named pip".
#
#    `--only-binary=:all:` is required when crossing platforms (pip
#    can't safely build sdists for a different arch from this host),
#    so every PyPI dep in the resolve must publish either a
#    `py3-none-any` wheel or a wheel for one of the manylinux
#    variants enumerated above.
PIP_VENV=$(mktemp -d -t eigsep-wh-pip.XXXXXX)
trap 'rm -rf "$PIP_VENV"' EXIT
uv venv --python "$PY" --seed --quiet "$PIP_VENV"
"$PIP_VENV/bin/pip" download \
    --python-version "$PY" \
    "${PIP_PLATFORM_ARGS[@]}" \
    --only-binary=:all: \
    --require-hashes \
    --dest "$OUT" \
    -r "$OUT/requirements.txt"

# 3. Build off-PyPI hardware wheels (e.g. casperfpga) for the target arch
#    and emit a hashed hardware-requirements.txt alongside requirements.txt.
#    install-field.sh consumes both.
./scripts/build-git-wheels.sh "$MANIFEST" "$OUT" "$PLATFORM"
python3 scripts/hardware_requirements.py "$MANIFEST" "$OUT"

# 4. Build the eigsep-field meta wheel itself into the wheelhouse, then
#    append its pin + sha256 to requirements.txt so install-field.sh can
#    install it offline under --require-hashes. Pure-Python, so a single
#    wheel works on any platform.
uv build --wheel --out-dir "$OUT"
python3 - "$MANIFEST" "$OUT" <<'PY'
import hashlib, sys, tomllib
from pathlib import Path
manifest_path, out_dir = Path(sys.argv[1]), Path(sys.argv[2])
version = tomllib.loads(manifest_path.read_text())["release"]
wheels = sorted(out_dir.glob(f"eigsep_field-{version}-*.whl"))
if len(wheels) != 1:
    sys.exit(
        f"expected 1 eigsep_field wheel at {version}, got "
        f"{[w.name for w in wheels]}"
    )
h = hashlib.sha256()
with wheels[0].open("rb") as f:
    for chunk in iter(lambda: f.read(1 << 20), b""):
        h.update(chunk)
req = out_dir / "requirements.txt"
with req.open("a") as f:
    f.write(f"\neigsep-field=={version} \\\n    --hash=sha256:{h.hexdigest()}\n")
print(f"appended eigsep-field=={version} to {req}")
PY

# 5. Sanity-check the wheelhouse contains every EIGSEP package at the
#    manifest-blessed version (catches sdist-only edge cases).
python3 scripts/check_wheelhouse.py "$MANIFEST" "$OUT"

echo
echo "wheelhouse built in $OUT ($(ls -1 "$OUT"/*.whl "$OUT"/*.tar.gz 2>/dev/null | wc -l) files)"
