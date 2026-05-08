#!/usr/bin/env bash
# Build off-PyPI hardware Python wheels declared in manifest.toml's
# [hardware.*] table. One wheel per entry is written to $OUT, built for
# the target platform (default: linux_aarch64, the field Pi nodes).
#
# When the host architecture already matches the target, builds natively.
# Otherwise cross-builds via docker with qemu-user emulation — so this
# requires docker + binfmt_misc/qemu-user-static registered on the host.
#
#   ./scripts/build-git-wheels.sh [manifest.toml] [wheels/] [platform]
set -euo pipefail

cd "$(dirname "$0")/.."

MANIFEST=${1:-manifest.toml}
OUT=${2:-wheels}
PLATFORM=${3:-$(python3 -c "import tomllib; print(tomllib.load(open('$MANIFEST','rb')).get('system',{}).get('platform','linux_aarch64'))")}
PY=${PY:-$(python3 -c "import tomllib; print(tomllib.load(open('$MANIFEST','rb'))['python'])")}

case "$PLATFORM" in
    linux_aarch64)
        docker_platform=linux/arm64
        target_uname=aarch64
        ;;
    linux_x86_64)
        docker_platform=linux/amd64
        target_uname=x86_64
        ;;
    *)
        echo "build-git-wheels: unsupported target platform: $PLATFORM" >&2
        exit 2
        ;;
esac

mapfile -t entries < <(python3 - "$MANIFEST" <<'EOF'
import sys, tomllib
m = tomllib.load(open(sys.argv[1], "rb"))
for name, entry in m.get("hardware", {}).items():
    print(f"{name}|{entry['source']}|{entry['tag']}|{entry['version']}")
EOF
)

if [[ ${#entries[@]} -eq 0 ]]; then
    echo "build-git-wheels: no [hardware.*] entries in $MANIFEST"
    exit 0
fi

mkdir -p "$OUT"
abs_out=$(cd "$OUT" && pwd)

# Strip --hash continuations from the main requirements.txt to produce a
# constraints file pip wheel will accept without flipping into
# --require-hashes mode (which it does whenever it sees a hash in any
# input file). Hardware-package transitive deps that happen to overlap
# with the main resolve (e.g. redis, IPython) get pinned to the
# main-resolve version this way; non-overlapping deps (katcp, tornado,
# tftpy, …) are pulled at whatever pip resolves naturally.
constraints="$abs_out/.constraints.txt"
if [[ -f "$abs_out/requirements.txt" ]]; then
    python3 - "$abs_out/requirements.txt" "$constraints" <<'PY'
import sys

src_lines = open(sys.argv[1]).read().splitlines(keepends=True)
out_lines = []

for line in src_lines:
    if line.lstrip().startswith("--hash="):
        if out_lines and out_lines[-1].rstrip().endswith("\\"):
            prev = out_lines[-1]
            newline = "\n" if prev.endswith("\n") else ""
            prev = prev[:-1] if newline else prev
            if prev.endswith("\\"):
                prev = prev[:-1]
            out_lines[-1] = prev.rstrip() + newline
        continue
    out_lines.append(line)

open(sys.argv[2], "w").write("".join(out_lines))
PY
else
    : > "$constraints"
fi

host_arch=$(uname -m)
cross=0
if [[ "$host_arch" != "$target_uname" ]]; then
    cross=1
    if ! command -v docker >/dev/null 2>&1; then
        echo "build-git-wheels: cross-build needs docker (host=$host_arch, target=$target_uname)" >&2
        exit 2
    fi
fi

for line in "${entries[@]}"; do
    IFS='|' read -r name source tag version <<< "$line"
    echo "build-git-wheels: $name $tag (target $PLATFORM, py$PY)"

    # Skip if already built.
    if ls "$abs_out/${name}-${version}-"*.whl >/dev/null 2>&1; then
        echo "  already present in $OUT, skipping"
        continue
    fi

    # No --no-deps: hardware packages carry transitive PyPI deps
    # (casperfpga -> katcp, tornado, tftpy, future, …) that the chroot
    # installer has to find offline in /opt/eigsep/wheels. pip wheel
    # builds the hardware package itself plus downloads/builds wheels
    # for every transitive dep into $OUT, constrained against the main
    # resolve so overlapping packages (redis, IPython, …) stay aligned.
    url="${source%.git}.git@${tag}"
    if [[ $cross -eq 1 ]]; then
        docker run --rm --platform "$docker_platform" \
            -v "$abs_out:/out" \
            "python:${PY}-slim" \
            bash -c "set -e; \
                apt-get update -q; \
                DEBIAN_FRONTEND=noninteractive apt-get install -y -q --no-install-recommends git gcc build-essential; \
                pip wheel --constraint /out/.constraints.txt --wheel-dir /out 'git+${url}'"
    else
        pip wheel --constraint "$constraints" --wheel-dir "$abs_out" "git+${url}"
    fi
done

rm -f "$constraints"

echo "build-git-wheels: done"
