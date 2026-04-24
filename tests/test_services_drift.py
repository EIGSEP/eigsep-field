"""Belt-and-suspenders drift check for sibling-owned service unit files.

Mirrors the ``services-drift`` CI job. Skipped when the network is
unavailable (so a fresh clone without internet still passes), but the CI
job runs with network and fails hard on drift.

Also includes a pure-local structural check: every local unit file under
``files/systemd/`` has a matching ``[services.<name>]`` entry and vice
versa.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "scripts"
MANIFEST = REPO_ROOT / "manifest.toml"
SYSTEMD_DIR = (
    REPO_ROOT
    / "image"
    / "pi-gen-config"
    / "stage-eigsep"
    / "files"
    / "systemd"
)


def _load_checker():
    sys.path.insert(0, str(SCRIPTS))
    try:
        import check_services_drift

        return check_services_drift
    finally:
        if str(SCRIPTS) in sys.path:
            sys.path.remove(str(SCRIPTS))


def _gh_ready() -> bool:
    """True iff `gh` is installed and authenticated (CI-equivalent env)."""
    if shutil.which("gh") is None:
        return False
    r = subprocess.run(
        ["gh", "auth", "status"], capture_output=True, text=True
    )
    return r.returncode == 0


def test_files_systemd_and_manifest_agree():
    """Every local/sibling unit file has a manifest entry (and vice versa)."""
    manifest = tomllib.loads(MANIFEST.read_text())
    services = manifest.get("services", {})
    manifest_units = {
        entry["unit"]
        for entry in services.values()
        if entry.get("kind") in ("local", "sibling")
    }
    disk_units = {
        p.name
        for p in SYSTEMD_DIR.iterdir()
        if p.suffix in (".service", ".target")
    }
    missing_on_disk = manifest_units - disk_units
    orphan_on_disk = disk_units - manifest_units
    msgs = []
    if missing_on_disk:
        msgs.append(
            f"manifest references unit files not present in "
            f"{SYSTEMD_DIR.relative_to(REPO_ROOT)}: "
            f"{sorted(missing_on_disk)}"
        )
    if orphan_on_disk:
        msgs.append(
            f"unit files present with no [services.*] entry: "
            f"{sorted(orphan_on_disk)}"
        )
    assert not msgs, "\n".join(msgs)


def test_tag_alignment_with_peer_package():
    """Service tag must match its peer package tag (picohost, eigsep-vna)."""
    checker = _load_checker()
    manifest = tomllib.loads(MANIFEST.read_text())
    services = manifest.get("services", {})
    problems: list[str] = []
    for name, entry in services.items():
        if entry.get("kind") != "sibling":
            continue
        problems.extend(checker._check_tag_alignment(manifest, name, entry))
    assert not problems, "\n".join(problems)


def test_sibling_units_match_upstream():
    """Full semantic diff against pinned upstream — needs authed gh CLI."""
    if not _gh_ready():
        pytest.skip(
            "gh CLI not authenticated; CI sets GH_TOKEN and enforces this"
        )
    checker = _load_checker()
    rc = checker.check(quiet=True)
    assert rc == 0, (
        "sibling unit files drifted from pinned upstream; "
        "run `python3 scripts/check_services_drift.py` for details"
    )
