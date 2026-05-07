"""Tests for role-aware firmware/hardware checks.

Doctor's ``_check_firmware`` and the hardware loop in ``_check_packages``
now consult ``[firmware.*].roles`` and ``[hardware.*].roles`` so a panda
Pi doesn't FAIL on missing rfsoc bitstream + casperfpga (which only the
backend uses).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from eigsep_field import cli
from eigsep_field._services import RoleConfig, entry_for_role


def test_entry_for_role_no_roles_field_matches_all() -> None:
    assert entry_for_role({}, "panda")
    assert entry_for_role({}, "backend")
    assert entry_for_role({}, None)


def test_entry_for_role_explicit_match() -> None:
    assert entry_for_role({"roles": ["backend"]}, "backend")
    assert not entry_for_role({"roles": ["backend"]}, "panda")


def test_entry_for_role_multiple_listed() -> None:
    e = {"roles": ["panda", "backend"]}
    assert entry_for_role(e, "panda")
    assert entry_for_role(e, "backend")
    assert not entry_for_role(e, "dhcp-master")


def test_entry_for_role_unset_role_skips_role_scoped() -> None:
    """A freshly-flashed Pi with no /etc/eigsep/role yet should not have
    the doctor fail on role-scoped entries — they're "not yet known to
    apply", not missing."""
    assert not entry_for_role({"roles": ["backend"]}, None)


@pytest.fixture
def fake_firmware_root(tmp_path: Path, monkeypatch) -> Path:
    """Redirect _check_firmware's hardcoded /opt/eigsep/firmware to tmp."""

    real_path = cli.Path

    def fake_path(*args, **kwargs):
        if args and args[0] == "/opt/eigsep/firmware":
            return tmp_path
        return real_path(*args, **kwargs)

    monkeypatch.setattr(cli, "Path", fake_path)
    return tmp_path


def test_check_firmware_skips_non_role(fake_firmware_root: Path) -> None:
    manifest = {
        "firmware": {
            "rfsoc_bitstream": {
                "asset": "bs.npz",
                "roles": ["backend"],
                "sha256": "",
            },
        }
    }
    ok, problems = cli._check_firmware(manifest, RoleConfig("panda", False))
    assert problems == []
    assert any("skipped" in line for line in ok)


def test_check_firmware_flags_missing_on_matching_role(
    fake_firmware_root: Path,
) -> None:
    manifest = {
        "firmware": {
            "rfsoc_bitstream": {
                "asset": "bs.npz",
                "roles": ["backend"],
                "sha256": "",
            },
        }
    }
    ok, problems = cli._check_firmware(manifest, RoleConfig("backend", False))
    assert problems  # asset doesn't exist, so it's flagged
    assert any("rfsoc_bitstream" in p for p in problems)


def test_check_firmware_no_roles_field_checks_all_roles(
    fake_firmware_root: Path,
) -> None:
    """Back-compat: a [firmware.*] entry without `roles` is required on
    every Pi."""
    manifest = {
        "firmware": {
            "global_blob": {"asset": "x.bin", "sha256": ""},
        }
    }
    ok, problems = cli._check_firmware(manifest, RoleConfig("panda", False))
    assert problems
    assert all("skipped" not in line for line in ok)


def test_check_packages_skips_non_role_hardware(monkeypatch) -> None:
    """Hardware entries gated by roles don't FAIL on a non-matching Pi."""
    manifest = {
        "packages": {},
        "hardware": {
            "casperfpga": {
                "version": "0.7.1",
                "roles": ["backend"],
            }
        },
    }
    ok, problems = cli._check_packages(manifest, RoleConfig("panda", False))
    assert problems == []
    assert any("skipped" in line for line in ok)


def test_check_packages_requires_hardware_on_matching_role(
    monkeypatch,
) -> None:
    """Per feedback_casperfpga_backend memory: missing casperfpga on
    backend is a real bug, not noise — the role gate must NOT swallow it."""
    manifest = {
        "packages": {},
        "hardware": {
            "casperfpga": {
                "version": "0.7.1",
                "roles": ["backend"],
            }
        },
    }
    ok, problems = cli._check_packages(manifest, RoleConfig("backend", False))
    assert any("casperfpga" in p for p in problems)
