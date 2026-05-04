"""Verify a built wheelhouse contains every EIGSEP package at the manifest version.

Run after the wheelhouse download step. Fails non-zero if any EIGSEP
package is missing or the version on disk does not match manifest.toml.
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path


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
