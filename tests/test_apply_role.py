"""Tests for ``eigsep_field.cli._apply_role_static_ip``.

The backend Pi must own ``10.10.10.10/24`` on eth0 before
isc-dhcp-server starts; the panda Pi gets ``10.10.10.11/24`` so it's
reachable even when the backend Pi isn't on the wire. Trixie pi-gen
Lite uses NetworkManager (the ``dhcpcd`` package is present but ships
no systemd unit), so the implementation writes a NetworkManager keyfile
and asks ``nmcli`` to reload + activate it.
"""

from __future__ import annotations

import pytest

from eigsep_field._services import RoleConfig


@pytest.fixture
def fake_nmcli(monkeypatch):
    """Capture nmcli calls; default to success."""
    calls: list[tuple[str, ...]] = []
    rcs: dict[tuple[str, ...], tuple[int, str]] = {}

    def _nmcli(*args: str) -> tuple[int, str]:
        calls.append(args)
        return rcs.get(args, (0, ""))

    from eigsep_field import cli

    monkeypatch.setattr(cli, "nmcli", _nmcli)
    return calls, rcs


def test_unknown_role_is_noop(tmp_path, fake_nmcli):
    from eigsep_field.cli import _apply_role_static_ip

    calls, _ = fake_nmcli
    rc = _apply_role_static_ip(RoleConfig(role=None), nm_dir=tmp_path)
    assert rc == 0
    assert calls == []
    assert list(tmp_path.iterdir()) == []


def test_backend_writes_keyfile_and_reloads(tmp_path, fake_nmcli):
    from eigsep_field.cli import _apply_role_static_ip

    calls, _ = fake_nmcli
    rc = _apply_role_static_ip(RoleConfig(role="backend"), nm_dir=tmp_path)
    assert rc == 0
    keyfile = tmp_path / "eigsep-eth0.nmconnection"
    assert keyfile.exists()
    body = keyfile.read_text()
    assert "interface-name=eth0" in body
    assert "method=manual" in body
    assert "address1=10.10.10.10/24" in body
    # NetworkManager refuses world-readable keyfiles.
    assert (keyfile.stat().st_mode & 0o777) == 0o600
    assert ("connection", "reload") in calls
    assert ("connection", "up", "eigsep-eth0") in calls


def test_panda_writes_panda_ip(tmp_path, fake_nmcli):
    """Panda gets 10.10.10.11/24 — symmetric coverage to backend."""
    from eigsep_field.cli import _apply_role_static_ip

    calls, _ = fake_nmcli
    rc = _apply_role_static_ip(RoleConfig(role="panda"), nm_dir=tmp_path)
    assert rc == 0
    keyfile = tmp_path / "eigsep-eth0.nmconnection"
    body = keyfile.read_text()
    assert "address1=10.10.10.11/24" in body
    assert "address1=10.10.10.10/24" not in body
    assert ("connection", "reload") in calls
    assert ("connection", "up", "eigsep-eth0") in calls


def test_keyfile_overwritten_idempotently(tmp_path, fake_nmcli):
    from eigsep_field.cli import _apply_role_static_ip

    cfg = RoleConfig(role="backend")
    keyfile = tmp_path / "eigsep-eth0.nmconnection"
    keyfile.write_text("stale junk\n")
    keyfile.chmod(0o644)

    rc = _apply_role_static_ip(cfg, nm_dir=tmp_path)
    assert rc == 0
    body = keyfile.read_text()
    assert "stale junk" not in body
    assert "address1=10.10.10.10/24" in body
    assert (keyfile.stat().st_mode & 0o777) == 0o600


def test_nm_dir_missing_warns(tmp_path, fake_nmcli, capsys):
    from eigsep_field.cli import _apply_role_static_ip

    missing = tmp_path / "does-not-exist"
    rc = _apply_role_static_ip(RoleConfig(role="backend"), nm_dir=missing)
    assert rc == 1
    err = capsys.readouterr().err
    assert "missing" in err
    calls, _ = fake_nmcli
    assert calls == []


def test_nmcli_reload_failure_returns_nonzero(tmp_path, fake_nmcli):
    from eigsep_field.cli import _apply_role_static_ip

    calls, rcs = fake_nmcli
    rcs[("connection", "reload")] = (4, "boom")
    rc = _apply_role_static_ip(RoleConfig(role="backend"), nm_dir=tmp_path)
    assert rc == 1
    # File was still written, but `up` should NOT be attempted after reload fails.
    assert (tmp_path / "eigsep-eth0.nmconnection").exists()
    assert ("connection", "up", "eigsep-eth0") not in calls


def test_nmcli_up_failure_returns_nonzero(tmp_path, fake_nmcli):
    from eigsep_field.cli import _apply_role_static_ip

    _, rcs = fake_nmcli
    rcs[("connection", "up", "eigsep-eth0")] = (10, "no carrier")
    rc = _apply_role_static_ip(RoleConfig(role="backend"), nm_dir=tmp_path)
    assert rc == 1


def test_does_not_touch_dhcpcd_conf(tmp_path, fake_nmcli, monkeypatch):
    """Regression: the old implementation wrote /etc/dhcpcd.conf and
    restarted dhcpcd.service. Trixie has no dhcpcd unit; both must go."""
    from eigsep_field import cli

    systemctl_calls: list[tuple[str, ...]] = []

    def _systemctl(*args: str) -> tuple[int, str]:
        systemctl_calls.append(args)
        return 0, ""

    monkeypatch.setattr(cli, "systemctl", _systemctl)

    rc = cli._apply_role_static_ip(RoleConfig(role="backend"), nm_dir=tmp_path)
    assert rc == 0
    # No dhcpcd.service interaction.
    for call in systemctl_calls:
        assert "dhcpcd.service" not in call
