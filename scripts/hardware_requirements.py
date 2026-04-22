"""Emit hardware-requirements.txt with sha256 hashes for each [hardware.*] wheel.

Expects the wheels to already be present in the output directory (produced
by scripts/build-git-wheels.sh). Writes a pip-style requirements file with
--require-hashes-compatible hashes so install-field.sh can consume it
offline.
"""

from __future__ import annotations

import hashlib
import sys
import tomllib
from pathlib import Path


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main(argv: list[str]) -> int:
    manifest_path = Path(argv[1])
    out_dir = Path(argv[2])
    manifest = tomllib.loads(manifest_path.read_text())

    hardware = manifest.get("hardware", {})
    if not hardware:
        return 0

    lines: list[str] = []
    for name, entry in hardware.items():
        version = entry["version"]
        matches = sorted(out_dir.glob(f"{name}-{version}-*.whl"))
        if not matches:
            print(
                f"hardware_requirements: no wheel for {name}=={version} "
                f"in {out_dir} — run build-git-wheels.sh first",
                file=sys.stderr,
            )
            return 1
        if len(matches) > 1:
            print(
                f"hardware_requirements: multiple wheels for {name}=={version} "
                f"in {out_dir}: {[p.name for p in matches]}",
                file=sys.stderr,
            )
            return 1
        wheel = matches[0]
        digest = _sha256(wheel)
        lines.append(f"{name}=={version} \\")
        lines.append(f"    --hash=sha256:{digest}")

    (out_dir / "hardware-requirements.txt").write_text("\n".join(lines) + "\n")
    print(
        f"hardware_requirements: wrote {out_dir / 'hardware-requirements.txt'} "
        f"({len(hardware)} package(s))"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
