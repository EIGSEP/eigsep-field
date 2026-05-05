"""Local drift check for firmware mirrors.

Mirrors the ``firmware-drift`` CI job. Pure-local (no network), so it
runs on a fresh clone with no extra setup.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "scripts"


def _load_checker():
    sys.path.insert(0, str(SCRIPTS))
    try:
        import check_firmware_drift

        return check_firmware_drift
    finally:
        if str(SCRIPTS) in sys.path:
            sys.path.remove(str(SCRIPTS))


def test_firmware_mirrors_match_top_level():
    checker = _load_checker()
    rc = checker.check(quiet=True)
    assert rc == 0, (
        "firmware/<dir>/manifest.toml drifted from top-level "
        "[firmware.*]; run `python3 scripts/check_firmware_drift.py` "
        "for details"
    )
