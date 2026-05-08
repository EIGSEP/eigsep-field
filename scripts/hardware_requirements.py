"""Emit hardware-requirements.txt with sha256 hashes.

Covers each [hardware.*] wheel from manifest.toml plus every transitive
PyPI dep that build-git-wheels.sh dropped into the wheelhouse on top of
the main requirements.txt resolve. The chroot installer feeds this file
to ``pip install --no-index --require-hashes``, so anything casperfpga
imports must be pinned + hashed here unless the main requirements.txt
already covers it.

Run order: after build-git-wheels.sh, before the eigsep-field meta wheel
gets appended to requirements.txt — so wheels not in main requirements
at this point are exactly the hardware-introduced set.
"""

from __future__ import annotations

import hashlib
import re
import sys
import tomllib
from pathlib import Path


_WHEEL_FILENAME_RE = re.compile(
    r"^(?P<name>[A-Za-z0-9_.]+)-(?P<version>[^-]+)-.+\.whl$"
)
_REQ_PIN_RE = re.compile(
    r"^(?P<name>[A-Za-z0-9_.\-]+)==(?P<version>[^\s\\]+)", re.MULTILINE
)


def _canonical(name: str) -> str:
    """PEP 503 canonical form: lowercase, runs of [-_.] collapsed to '-'."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_main_pins(req_path: Path) -> set[tuple[str, str]]:
    if not req_path.is_file():
        return set()
    text = req_path.read_text()
    return {
        (_canonical(m.group("name")), m.group("version"))
        for m in _REQ_PIN_RE.finditer(text)
    }


def _wheel_pin(path: Path) -> tuple[str, str] | None:
    m = _WHEEL_FILENAME_RE.match(path.name)
    if not m:
        return None
    return (_canonical(m.group("name")), m.group("version"))


def _emit(name: str, version: str, wheel: Path) -> list[str]:
    return [f"{name}=={version} \\", f"    --hash=sha256:{_sha256(wheel)}"]


def main(argv: list[str]) -> int:
    manifest_path = Path(argv[1])
    out_dir = Path(argv[2])
    manifest = tomllib.loads(manifest_path.read_text())

    hardware = manifest.get("hardware", {})
    if not hardware:
        return 0

    main_pins = _read_main_pins(out_dir / "requirements.txt")
    declared_hardware = {_canonical(name) for name in hardware}

    lines: list[str] = []
    seen: set[tuple[str, str]] = set()

    # 1. The declared [hardware.*] wheels themselves, in manifest order.
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
        lines.extend(_emit(name, version, wheel))
        seen.add((_canonical(name), version))

    # 2. Anything build-git-wheels.sh added to the wheelhouse that the
    #    main resolve didn't cover. Emit alphabetically for deterministic
    #    output.
    extras: list[tuple[str, str, Path]] = []
    for wheel in sorted(out_dir.glob("*.whl")):
        pin = _wheel_pin(wheel)
        if pin is None:
            continue
        name, version = pin
        if name in declared_hardware:
            continue
        if pin in main_pins:
            continue
        if pin in seen:
            continue
        extras.append((name, version, wheel))
        seen.add(pin)

    for name, version, wheel in extras:
        lines.extend(_emit(name, version, wheel))

    (out_dir / "hardware-requirements.txt").write_text("\n".join(lines) + "\n")
    print(
        f"hardware_requirements: wrote {out_dir / 'hardware-requirements.txt'} "
        f"({len(hardware)} hardware + {len(extras)} transitive)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
