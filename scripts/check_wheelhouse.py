"""Verify a built wheelhouse contains every EIGSEP package at the manifest version.

Run after the full wheelhouse has been assembled, including the later-added
hardware wheels and the ``eigsep-field`` meta wheel. Fails non-zero if any
required package is missing or the version on disk does not match
manifest.toml.
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

# Lower bounds matching the `build-system.requires` declared by sibling
# source trees (eigsep_observing, eigsep_redis, picohost, ...). If a
# sibling raises its floor, raise it here too; a stale wheelhouse with
# an older wheel would otherwise pass this check but fail the offline
# editable install on the Pi.
_BUILD_DEP_MIN = {"setuptools": (65,), "wheel": (0,)}

_WHEEL_VERSION_RE = re.compile(
    r"^(?P<name>[A-Za-z0-9_.]+)-(?P<version>[^-]+)-.+\.whl$"
)


def _parse_version(version: str) -> tuple[int, ...]:
    """Return the leading numeric components of ``version`` as a tuple.

    Stops at the first non-numeric segment (handles pre/post/dev suffixes
    like ``75.6.0rc1``). Sufficient for setuptools/wheel which use plain
    dotted-integer release versions.
    """
    parts: list[int] = []
    for chunk in version.split("."):
        m = re.match(r"\d+", chunk)
        if not m:
            break
        parts.append(int(m.group()))
    return tuple(parts)


def main(argv: list[str]) -> int:
    manifest_path = Path(argv[1])
    wheel_dir = Path(argv[2])
    manifest = tomllib.loads(manifest_path.read_text())

    missing: list[str] = []

    meta_version = manifest["release"]
    meta_matches = list(wheel_dir.glob(f"eigsep_field-{meta_version}-*.whl"))
    if not meta_matches:
        missing.append(f"eigsep-field=={meta_version} (meta)")

    for entry in manifest["packages"].values():
        name = entry["pypi"].replace("-", "_")
        version = entry["version"]
        matches = list(wheel_dir.glob(f"{name}-{version}-*.whl"))
        matches += list(wheel_dir.glob(f"{name}-{version}.tar.gz"))
        if not matches:
            missing.append(f"{name}=={version}")

    for name, entry in manifest.get("hardware", {}).items():
        version = entry["version"]
        matches = list(wheel_dir.glob(f"{name}-{version}-*.whl"))
        if not matches:
            missing.append(f"{name}=={version} (hardware)")

    # PEP 517 build deps for siblings whose `build-system.requires` lists
    # setuptools + wheel. Required on the Pi: `eigsep-field patch` runs an
    # editable install which triggers an isolated build, and the on-Pi uv
    # config (offline + no-index + find-links=/opt/eigsep/wheels) means
    # these wheels must be resolvable from this directory.
    for name, floor in _BUILD_DEP_MIN.items():
        wheels = list(wheel_dir.glob(f"{name}-*.whl"))
        if not wheels:
            missing.append(f"{name} (build dep)")
            continue
        # A stale wheelhouse can hold an older wheel that satisfies the
        # glob but is below the sibling build floor; reject it explicitly.
        best = max(
            (
                _parse_version(m.group("version"))
                for w in wheels
                if (m := _WHEEL_VERSION_RE.match(w.name))
            ),
            default=(),
        )
        if best < floor:
            min_str = ".".join(str(p) for p in floor)
            best_str = ".".join(str(p) for p in best) if best else "?"
            missing.append(f"{name}>={min_str} (build dep; found {best_str})")

    if missing:
        print("missing from wheelhouse:", file=sys.stderr)
        for m in missing:
            print(f"  - {m}", file=sys.stderr)
        return 1
    n_hw = len(manifest.get("hardware", {}))
    hw_tail = f" + {n_hw} hardware" if n_hw else ""
    print(
        f"wheelhouse OK: {len(manifest['packages'])} EIGSEP packages present"
        f"{hw_tail}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
