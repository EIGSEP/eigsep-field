"""Tests for ``eigsep_field._services.resolve_boot_role_conf``.

Trixie's pi-gen mounts the SD card's FAT boot partition at
``/boot/firmware`` while older Bullseye/Bookworm mounted it at ``/boot``.
The resolver must prefer the Trixie path but fall back gracefully so
existing field SD cards keep working through the transition.
"""

from __future__ import annotations

from pathlib import Path

from eigsep_field._services import resolve_boot_role_conf


def test_prefers_first_existing(tmp_path: Path) -> None:
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.write_text("role = panda\n")
    b.write_text("role = backend\n")
    assert resolve_boot_role_conf((a, b)) == a


def test_falls_back_when_first_missing(tmp_path: Path) -> None:
    a = tmp_path / "missing"
    b = tmp_path / "present"
    b.write_text("role = backend\n")
    assert resolve_boot_role_conf((a, b)) == b


def test_returns_preferred_path_when_none_exist(tmp_path: Path) -> None:
    a = tmp_path / "a"
    b = tmp_path / "b"
    # Returning the preferred candidate (rather than None) lets callers
    # build a clean error message pointed at the canonical location.
    assert resolve_boot_role_conf((a, b)) == a


def test_default_candidates_are_trixie_then_legacy() -> None:
    from eigsep_field._services import BOOT_ROLE_CONF_CANDIDATES

    assert BOOT_ROLE_CONF_CANDIDATES == (
        Path("/boot/firmware/eigsep-role.conf"),
        Path("/boot/eigsep-role.conf"),
    )
