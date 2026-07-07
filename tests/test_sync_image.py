"""Tests for eigsep_field._sync — fake-root file staging."""

from __future__ import annotations

from pathlib import Path

import pytest

from eigsep_field import _sync


REPO = Path(__file__).resolve().parent.parent


@pytest.fixture
def tree(tmp_path):
    """Minimal eigsep-field tree with a stage files/ dir."""
    t = tmp_path / "tree"
    f = t / "image/pi-gen-config/stage-eigsep/00-eigsep-install/files"
    (f / "systemd").mkdir(parents=True)
    (f / "systemd" / "demo.service").write_text("[Unit]\nA=1\n")
    (f / "systemd" / "chrony-wait.service.d").mkdir()
    (f / "systemd" / "chrony-wait.service.d" / "eigsep.conf").write_text(
        "[Install]\n"
    )
    (f / "udev").mkdir()
    (f / "udev" / "usb-demo.rules").write_text("RULE\n")
    (t / "manifest.toml").write_text('release = "2026.4.0"\n')
    return t


@pytest.fixture
def ctx(tree, tmp_path):
    import tomllib

    manifest = tomllib.loads((tree / "manifest.toml").read_text())
    return _sync.SyncContext(
        tree=tree, manifest=manifest, root=tmp_path / "root", dry_run=False
    )


def test_dest_resolves_under_root(ctx):
    assert ctx.dest("/etc/motd") == ctx.root / "etc/motd"


def test_install_new_file(ctx, tree):
    entry = _sync.FileMapEntry("systemd/*.service", "/etc/systemd/system")
    src = _sync.files_dir(tree) / "systemd" / "demo.service"
    assert _sync.install_file(ctx, entry, src) is True
    dest = ctx.dest("/etc/systemd/system/demo.service")
    assert dest.read_text() == "[Unit]\nA=1\n"
    assert (dest.stat().st_mode & 0o777) == 0o644


def test_install_unchanged_is_noop(ctx, tree):
    entry = _sync.FileMapEntry("systemd/*.service", "/etc/systemd/system")
    src = _sync.files_dir(tree) / "systemd" / "demo.service"
    _sync.install_file(ctx, entry, src)
    assert _sync.install_file(ctx, entry, src) is False


def test_install_preserve_parent_dropin(ctx, tree):
    entry = _sync.FileMapEntry(
        "systemd/*.service.d/*.conf",
        "/etc/systemd/system",
        preserve_parent=True,
    )
    src = _sync.files_dir(tree) / "systemd/chrony-wait.service.d/eigsep.conf"
    assert _sync.install_file(ctx, entry, src) is True
    assert ctx.dest(
        "/etc/systemd/system/chrony-wait.service.d/eigsep.conf"
    ).exists()


def test_dry_run_writes_nothing(ctx, tree):
    ctx.dry_run = True
    entry = _sync.FileMapEntry("udev/*.rules", "/etc/udev/rules.d")
    src = _sync.files_dir(tree) / "udev" / "usb-demo.rules"
    assert _sync.install_file(ctx, entry, src) is True
    assert not ctx.dest("/etc/udev/rules.d/usb-demo.rules").exists()


def test_iter_map_files_missing_nonglob_raises(tmp_path):
    t = tmp_path / "empty"
    _sync.files_dir(t).mkdir(parents=True)
    with pytest.raises(FileNotFoundError):
        _sync.iter_map_files(t)


def test_file_map_covers_real_repo():
    pairs = _sync.iter_map_files(REPO)
    srcs = {p.name for _, p in pairs}
    assert "picomanager.service" in srcs
    assert "usb-cmt-vna.rules" in srcs
    assert "motd" in srcs
    assert "CHEATSHEET.md" in srcs


def test_render_template_release_and_dev_banner():
    text = "# release {{release}}\n{{dev_banner}}\nbody\n"
    out = _sync.render_template(text, "2026.4.0", "*** DEV abc ***")
    assert "release 2026.4.0" in out
    assert "*** DEV abc ***" in out


def test_render_template_strips_banner_line_when_blessed():
    text = "# release {{release}}\n{{dev_banner}}\nbody\n"
    out = _sync.render_template(text, "2026.4.0", "")
    assert "{{dev_banner}}" not in out
    assert out.splitlines() == ["# release 2026.4.0", "body"]


def test_read_dev_banner(ctx):
    etc = ctx.dest("/etc/eigsep")
    etc.mkdir(parents=True)
    (etc / "manifest.toml").write_text(
        'release = "2026.3.0"\n[image]\ndev = true\nsha = "abc1234"\n'
    )
    assert "abc1234" in _sync.read_dev_banner(ctx)


def test_read_dev_banner_blessed_or_missing(ctx):
    assert _sync.read_dev_banner(ctx) == ""


def test_refresh_etc_manifest_preserves_image_block(ctx):
    etc = ctx.dest("/etc/eigsep")
    etc.mkdir(parents=True)
    (etc / "manifest.toml").write_text(
        'release = "2026.3.0"\n[image]\ndev = true\nsha = "abc1234"\n'
    )
    _sync.refresh_etc_manifest(ctx)
    import tomllib

    m = tomllib.loads((etc / "manifest.toml").read_text())
    assert m["release"] == "2026.4.0"
    assert m["image"] == {"dev": True, "sha": "abc1234"}


def test_append_redis_includes_idempotent(ctx):
    redis = ctx.dest("/etc/redis")
    redis.mkdir(parents=True)
    conf = redis / "redis.conf"
    conf.write_text("bind 127.0.0.1\n")
    _sync.append_redis_includes(ctx)
    _sync.append_redis_includes(ctx)
    body = conf.read_text()
    assert body.count("include /etc/redis/redis.conf.d/eigsep.conf") == 1
    assert body.count("include /etc/redis/redis.conf.d/eigsep-role.conf") == 1


def test_sudoers_gate_rejects_bad_file(ctx, tree, monkeypatch):
    f = _sync.files_dir(tree) / "sudoers.d"
    f.mkdir()
    (f / "eigsep-field").write_text("syntactically wrong\n")
    monkeypatch.setattr(_sync, "_sudoers_ok", lambda data: False)
    entry = _sync.FileMapEntry(
        "sudoers.d/eigsep-field",
        "/etc/sudoers.d",
        mode=0o440,
        special="sudoers",
    )
    src = f / "eigsep-field"
    assert _sync.install_file(ctx, entry, src) is False
    assert ctx.failures == 1
    assert not ctx.dest("/etc/sudoers.d/eigsep-field").exists()


def test_template_files_render_on_install(ctx, tree):
    f = _sync.files_dir(tree) / "etc-eigsep"
    f.mkdir(parents=True)
    (f / "motd").write_text("release {{release}}\n{{dev_banner}}\n")
    entry = _sync.FileMapEntry("etc-eigsep/motd", "/etc", special="template")
    _sync.install_file(ctx, entry, f / "motd")
    body = ctx.dest("/etc/motd").read_text()
    assert "release 2026.4.0" in body
    assert "{{dev_banner}}" not in body


@pytest.fixture
def fake_systemctl(monkeypatch):
    calls: list[tuple[str, ...]] = []

    def _sc(*args):
        calls.append(args)
        return 0, ""

    monkeypatch.setattr(_sync, "systemctl", _sc)
    return calls


def _write_tombstones(tree, lines):
    p = tree / _sync.STAGE_REL / "removed-paths.txt"
    p.write_text("\n".join(lines) + "\n")


def test_removals_deletes_and_disables_unit(ctx, tree, fake_systemctl):
    _write_tombstones(
        tree, ["# gone", "/etc/systemd/system/eigsep-panda.service"]
    )
    stale = ctx.dest("/etc/systemd/system/eigsep-panda.service")
    stale.parent.mkdir(parents=True)
    stale.write_text("[Unit]\n")
    _sync.step_removals(ctx)
    assert not stale.exists()
    assert (
        "disable",
        "--now",
        "eigsep-panda.service",
    ) in fake_systemctl
    assert "eigsep-panda.service" in ctx.changed_units


def test_removals_missing_path_is_silent_noop(ctx, tree, fake_systemctl):
    _write_tombstones(tree, ["/etc/systemd/system/never-existed.service"])
    _sync.step_removals(ctx)
    assert fake_systemctl == []
    assert ctx.failures == 0


def test_removals_dry_run_keeps_file(ctx, tree, fake_systemctl):
    ctx.dry_run = True
    _write_tombstones(tree, ["/etc/old.conf"])
    old = ctx.dest("/etc/old.conf")
    old.parent.mkdir(parents=True)
    old.write_text("x")
    _sync.step_removals(ctx)
    assert old.exists()
    assert fake_systemctl == []
