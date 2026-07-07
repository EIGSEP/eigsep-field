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
