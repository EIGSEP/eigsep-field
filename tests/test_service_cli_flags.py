"""Tripwire: every long flag in a service unit's ExecStart must be
accepted by the binary's CLI.

``scripts/check_services_drift.py`` normalizes ExecStart down to
argv[0] basename so it can absorb path differences between the
dev-clone layout and the image layout. That choice means bogus argv
flags slip through: pico-firmware v3.1.1 shipped
``picohost/pico-manager.service`` with ``--config <path>`` that the
CLI never accepted, restart-looping ``picomanager.service`` on every
panda Pi until somebody flashed one and read the journal.

This test is the missing layer. For each ``[services.*]`` entry of
kind ``local`` or ``sibling`` whose ExecStart binary is not a wrapper,
it runs ``<binary> --help`` in the test interpreter's venv and
asserts that every ``--flag`` token in ExecStart appears in the help
text.

Limitations:
- Short flags (``-p``) are not checked. The regression we're guarding
  against was a long flag; short-flag mismatches are easier to spot
  in unit-file review.
- ``xvfb-run <flags> <real-binary>`` and ``python -m <module>`` units
  are skipped — the wrapper's flags would be compared against the
  wrong CLI. Two units today rely on these (``cmtvna.service``,
  ``eigsep-panda.service``). Revisit if a third wrapper shows up.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST = tomllib.loads((REPO_ROOT / "manifest.toml").read_text())
UNIT_DIR = (
    REPO_ROOT
    / "image"
    / "pi-gen-config"
    / "stage-eigsep"
    / "00-eigsep-install"
    / "files"
    / "systemd"
)

_WRAPPER_BINARIES = {"xvfb-run", "python", "python3"}
_FLAG_RE = re.compile(r"--[A-Za-z][A-Za-z0-9_-]*")


def _exec_start(unit_path: Path) -> str:
    for raw in unit_path.read_text().splitlines():
        s = raw.strip()
        if s.startswith("ExecStart="):
            return s[len("ExecStart=") :]
    raise AssertionError(f"No ExecStart= in {unit_path}")


def _parse_exec_start(exec_start: str) -> tuple[str, list[str]]:
    """Return (binary_path, list_of_long_flags) from an ExecStart value."""
    # Strip systemd's optional prefix sigils on the whole line (the
    # drift-check script does the equivalent normalization).
    cleaned = exec_start.lstrip("-+@!")
    tokens = cleaned.split()
    binary = tokens[0]
    flags = _FLAG_RE.findall(" ".join(tokens[1:]))
    return binary, flags


def _resolve(binary_path: str) -> Path | None:
    """The unit's image-layout path (``/opt/eigsep/venv/bin/foo``) does
    not exist in this test env; resolve by basename via ``PATH`` and
    fall back to the current interpreter's bin dir."""
    name = Path(binary_path).name
    found = shutil.which(name)
    if found is not None:
        return Path(found)
    cand = Path(sys.executable).parent / name
    return cand if cand.exists() else None


def _cases() -> list:
    out: list = []
    for svc_name, svc in MANIFEST.get("services", {}).items():
        if svc.get("kind") not in {"local", "sibling"}:
            continue
        unit = UNIT_DIR / svc["unit"]
        if not unit.exists() or unit.suffix != ".service":
            continue
        binary, flags = _parse_exec_start(_exec_start(unit))
        if not flags:
            continue
        out.append(pytest.param(svc_name, unit, binary, flags, id=svc_name))
    return out


@pytest.mark.parametrize("svc_name,unit_path,binary,flags", _cases())
def test_exec_start_flags_recognized(svc_name, unit_path, binary, flags):
    if Path(binary).name in _WRAPPER_BINARIES:
        pytest.skip(f"{Path(binary).name!r} wraps another binary; not parsed")
    resolved = _resolve(binary)
    if resolved is None:
        pytest.skip(
            f"{Path(binary).name!r} not installed in test env "
            f"(install eigsep-field with its blessed deps)"
        )
    proc = subprocess.run(
        [str(resolved), "--help"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert proc.returncode == 0, (
        f"{svc_name}: `{Path(resolved).name} --help` exited "
        f"{proc.returncode}.\nstderr: {proc.stderr!r}"
    )
    help_text = proc.stdout + proc.stderr
    missing = [f for f in flags if f not in help_text]
    assert not missing, (
        f"{svc_name}: {Path(resolved).name} does not accept "
        f"{missing}\n"
        f"  unit: {unit_path.relative_to(REPO_ROOT)}\n"
        f"  recognized flags in --help output:\n"
        + "\n".join(f"    {ln}" for ln in help_text.splitlines())
    )
