"""`eigsep-field services {start,stop,restart}` is role-gated.

The image is uniform — every Pi carries every unit file — so without a
role gate, ``services start eigsep_observe`` from the panda Pi would
happily try to drive the backend stack. The CLI refuses cross-role
mutations and reports the mismatch.
"""

from __future__ import annotations

from types import SimpleNamespace


def _patch_role(monkeypatch, role: str | None) -> None:
    from eigsep_field import _services, cli

    monkeypatch.setattr(
        cli, "parse_role_file", lambda _p: _services.RoleConfig(role=role)
    )


def _capture_systemctl(monkeypatch) -> list[tuple[str, ...]]:
    seen: list[tuple[str, ...]] = []

    def fake_systemctl(*args: str) -> tuple[int, str]:
        seen.append(tuple(args))
        return 0, ""

    from eigsep_field import cli

    monkeypatch.setattr(cli, "systemctl", fake_systemctl)
    return seen


def test_start_role_match_invokes_systemctl(monkeypatch):
    from eigsep_field import cli

    _patch_role(monkeypatch, "backend")
    seen = _capture_systemctl(monkeypatch)

    assert cli.main(["services", "start", "eigsep_observe"]) == 0
    assert seen == [("start", "eigsep-observe.service")]


def test_stop_role_match_invokes_systemctl(monkeypatch):
    from eigsep_field import cli

    _patch_role(monkeypatch, "panda")
    seen = _capture_systemctl(monkeypatch)

    assert cli.main(["services", "stop", "picomanager"]) == 0
    assert seen == [("stop", "picomanager.service")]


def test_restart_always_service_allowed_regardless_of_role(monkeypatch):
    from eigsep_field import cli

    _patch_role(monkeypatch, "panda")
    seen = _capture_systemctl(monkeypatch)

    # `redis` is activation = "always", so every role runs it.
    assert cli.main(["services", "restart", "redis"]) == 0
    assert seen == [("restart", "redis-server.service")]


def test_start_cross_role_refused(monkeypatch, capsys):
    from eigsep_field import cli

    _patch_role(monkeypatch, "panda")
    seen = _capture_systemctl(monkeypatch)

    rc = cli.main(["services", "start", "eigsep_observe"])
    assert rc == 2
    assert seen == []
    err = capsys.readouterr().err
    assert "refusing to start 'eigsep_observe'" in err
    assert "role=backend" in err
    assert "this Pi's role is panda" in err


def test_stop_cross_role_refused(monkeypatch, capsys):
    from eigsep_field import cli

    _patch_role(monkeypatch, "backend")
    seen = _capture_systemctl(monkeypatch)

    rc = cli.main(["services", "stop", "picomanager"])
    assert rc == 2
    assert seen == []
    assert "refusing to stop 'picomanager'" in capsys.readouterr().err


def test_restart_cross_role_now_refused(monkeypatch, capsys):
    """Regression: `restart` used to skip the gate. It no longer does."""
    from eigsep_field import cli

    _patch_role(monkeypatch, "panda")
    seen = _capture_systemctl(monkeypatch)

    rc = cli.main(["services", "restart", "eigsep_observe"])
    assert rc == 2
    assert seen == []
    assert "refusing to restart" in capsys.readouterr().err


def test_unset_role_refuses_role_services(monkeypatch, capsys):
    from eigsep_field import cli

    _patch_role(monkeypatch, None)
    seen = _capture_systemctl(monkeypatch)

    rc = cli.main(["services", "start", "picomanager"])
    assert rc == 2
    assert seen == []
    assert "this Pi's role is (unset)" in capsys.readouterr().err
