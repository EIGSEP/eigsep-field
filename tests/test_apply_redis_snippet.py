"""Tests for ``eigsep_field.cli._apply_redis_snippet``.

The backend Pi's Redis must run without RDB/AOF persistence — the
periodic bgsave fork stalls the co-located correlator read loop and
drops integrations — while every other role keeps stock persistence,
because the panda Pi's Redis is the system of record for one-shot
operator state (``pico_config``, ``pot_calibration``). The applier
re-points the ``eigsep-role.conf`` symlink (shipped by the image
pointing at persistent.conf) and restarts Redis, which only reads its
config at startup.
"""

from __future__ import annotations

import pytest

from eigsep_field._services import RoleConfig

RESTART = ("restart", "redis-server.service")


@pytest.fixture
def fake_systemctl(monkeypatch):
    """Capture systemctl calls; default to success."""
    calls: list[tuple[str, ...]] = []
    rcs: dict[tuple[str, ...], tuple[int, str]] = {}

    def _systemctl(*args: str) -> tuple[int, str]:
        calls.append(args)
        return rcs.get(args, (0, ""))

    from eigsep_field import cli

    monkeypatch.setattr(cli, "systemctl", _systemctl)
    return calls, rcs


@pytest.fixture
def staged(tmp_path):
    """Mimic the image layout: both snippets staged under the
    /etc/eigsep/redis analogue, default symlink pre-pointed at
    persistent.conf (00-run.sh ships it that way because a redis
    ``include`` of a missing file is fatal at startup).
    """
    src_dir = tmp_path / "etc-eigsep-redis"
    src_dir.mkdir()
    (src_dir / "ephemeral.conf").write_text('save ""\nappendonly no\n')
    (src_dir / "persistent.conf").write_text("# stock persistence\n")
    target = tmp_path / "redis.conf.d" / "eigsep-role.conf"
    target.parent.mkdir()
    target.symlink_to(src_dir / "persistent.conf")
    return src_dir, target


def test_reset_failed_clears_start_limit_before_restart(
    staged, fake_systemctl
):
    """A prior failed restart (e.g. the sync-image fatal-include
    window) trips StartLimitBurst, and systemd then rejects even a
    valid restart with "start request repeated too quickly" — so the
    applier must reset-failed first. Its rc is ignored: on a healthy
    unit there is nothing to reset."""
    from eigsep_field.cli import _apply_redis_snippet

    src_dir, target = staged
    calls, rcs = fake_systemctl
    reset = ("reset-failed", "redis-server.service")
    rcs[reset] = (1, "Unit redis-server.service not loaded.")
    rc = _apply_redis_snippet(
        RoleConfig(role="panda"), src_dir=src_dir, target=target
    )
    assert rc == 0
    assert calls.index(reset) < calls.index(RESTART)


def test_backend_links_ephemeral_and_restarts(staged, fake_systemctl):
    from eigsep_field.cli import _apply_redis_snippet

    src_dir, target = staged
    calls, _ = fake_systemctl
    rc = _apply_redis_snippet(
        RoleConfig(role="backend"), src_dir=src_dir, target=target
    )
    assert rc == 0
    assert target.readlink() == src_dir / "ephemeral.conf"
    assert RESTART in calls


def test_panda_keeps_persistent(staged, fake_systemctl):
    from eigsep_field.cli import _apply_redis_snippet

    src_dir, target = staged
    calls, _ = fake_systemctl
    rc = _apply_redis_snippet(
        RoleConfig(role="panda"), src_dir=src_dir, target=target
    )
    assert rc == 0
    assert target.readlink() == src_dir / "persistent.conf"
    assert RESTART in calls


def test_reroll_backend_to_panda_flips_link(staged, fake_systemctl):
    """Editing eigsep-role.conf and re-rolling must undo the backend
    policy — the symlink is rewritten, not appended to.
    """
    from eigsep_field.cli import _apply_redis_snippet

    src_dir, target = staged
    _apply_redis_snippet(
        RoleConfig(role="backend"), src_dir=src_dir, target=target
    )
    rc = _apply_redis_snippet(
        RoleConfig(role="panda"), src_dir=src_dir, target=target
    )
    assert rc == 0
    assert target.readlink() == src_dir / "persistent.conf"


def test_missing_snippet_warns_without_restart(tmp_path, fake_systemctl):
    """An empty snippet dir (image-build bug) must not take Redis down:
    no symlink rewrite, no restart, rc=1 so apply-role reports it.
    """
    from eigsep_field.cli import _apply_redis_snippet

    calls, _ = fake_systemctl
    src_dir = tmp_path / "empty"
    src_dir.mkdir()
    target = tmp_path / "eigsep-role.conf"
    rc = _apply_redis_snippet(
        RoleConfig(role="backend"), src_dir=src_dir, target=target
    )
    assert rc == 1
    assert not target.exists()
    assert calls == []


def test_restart_failure_is_reported(staged, fake_systemctl):
    from eigsep_field.cli import _apply_redis_snippet

    src_dir, target = staged
    _, rcs = fake_systemctl
    rcs[RESTART] = (1, "boom")
    rc = _apply_redis_snippet(
        RoleConfig(role="backend"), src_dir=src_dir, target=target
    )
    assert rc == 1
    # The symlink was already flipped before the restart attempt —
    # acceptable, the next apply re-runs both steps.
    assert target.readlink() == src_dir / "ephemeral.conf"
