"""Tests for ``eigsep_field._services.unit_health``.

The doctor's service check used to call ``is_active`` directly. That
flagged ``eigsep-first-boot.service`` (Type=oneshot, RemainAfterExit=no)
as unhealthy after a successful run, because oneshots return to
``inactive`` once their ExecStart exits. ``unit_health`` distinguishes
"ran successfully and exited" from "never ran" / "failed".
"""

from __future__ import annotations

import pytest

from eigsep_field import _services


@pytest.fixture
def fake_systemctl(monkeypatch):
    """Capture systemctl calls; return canned (rc, stdout) per arg-tuple."""
    calls: list[tuple[str, ...]] = []
    rcs: dict[tuple[str, ...], tuple[int, str]] = {}

    def _systemctl(*args: str) -> tuple[int, str]:
        calls.append(args)
        return rcs.get(args, (1, ""))

    monkeypatch.setattr(_services, "systemctl", _systemctl)
    return calls, rcs


def test_active_service_is_healthy(fake_systemctl):
    _, rcs = fake_systemctl
    rcs[("is-active", "--quiet", "redis-server.service")] = (0, "")
    healthy, state = _services.unit_health("redis-server.service")
    assert healthy is True
    assert state == "active"


def test_inactive_service_is_unhealthy(fake_systemctl):
    _, rcs = fake_systemctl
    rcs[("is-active", "--quiet", "redis-server.service")] = (3, "")
    rcs[
        (
            "show",
            "--value",
            "-p",
            "Type,RemainAfterExit,Result",
            "redis-server.service",
        )
    ] = (0, "simple\nno\nsuccess\n")
    healthy, state = _services.unit_health("redis-server.service")
    assert healthy is False
    assert state == "inactive"


def test_oneshot_clean_exit_is_healthy(fake_systemctl):
    """eigsep-first-boot.service after a successful run: Type=oneshot,
    RemainAfterExit=no, Result=success, but ActiveState=inactive."""
    _, rcs = fake_systemctl
    rcs[("is-active", "--quiet", "eigsep-first-boot.service")] = (3, "")
    rcs[
        (
            "show",
            "--value",
            "-p",
            "Type,RemainAfterExit,Result",
            "eigsep-first-boot.service",
        )
    ] = (0, "oneshot\nno\nsuccess\n")
    healthy, state = _services.unit_health("eigsep-first-boot.service")
    assert healthy is True
    assert state == "oneshot done"


def test_oneshot_failure_is_unhealthy(fake_systemctl):
    """A oneshot whose ExecStart exited non-zero must NOT be reported
    healthy — Result=exit-code, not success."""
    _, rcs = fake_systemctl
    rcs[("is-active", "--quiet", "eigsep-first-boot.service")] = (3, "")
    rcs[
        (
            "show",
            "--value",
            "-p",
            "Type,RemainAfterExit,Result",
            "eigsep-first-boot.service",
        )
    ] = (0, "oneshot\nno\nexit-code\n")
    healthy, state = _services.unit_health("eigsep-first-boot.service")
    assert healthy is False
    assert state == "inactive"


def test_oneshot_remain_yes_falls_through(fake_systemctl):
    """Type=oneshot with RemainAfterExit=yes stays active after success;
    is-active returns 0 and we never look at Result. Sanity check: the
    code path that consults `show` is gated on RemainAfterExit=no."""
    _, rcs = fake_systemctl
    rcs[("is-active", "--quiet", "stays-active.service")] = (0, "")
    healthy, state = _services.unit_health("stays-active.service")
    assert healthy is True
    assert state == "active"


def test_show_failure_is_unhealthy(fake_systemctl):
    """If systemctl show itself fails (unit doesn't exist, dbus broken),
    treat the service as unhealthy rather than crashing."""
    _, rcs = fake_systemctl
    rcs[("is-active", "--quiet", "ghost.service")] = (3, "")
    rcs[
        (
            "show",
            "--value",
            "-p",
            "Type,RemainAfterExit,Result",
            "ghost.service",
        )
    ] = (1, "")
    healthy, state = _services.unit_health("ghost.service")
    assert healthy is False
    assert state == "inactive"
