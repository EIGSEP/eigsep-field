"""Tests for eigsep_field._sync — fake-root file staging."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tarfile
import time
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


@pytest.mark.skipif(os.geteuid() == 0, reason="root bypasses file perms")
def test_install_file_dry_run_survives_unreadable_dest(ctx, tree):
    """Non-root --dry-run must not crash on a root-owned dest it can't
    read (real Pi: /etc/redis/redis.conf is 0640 redis:redis,
    /etc/sudoers.d/eigsep-field is 0440 root)."""
    entry = _sync.FileMapEntry("systemd/*.service", "/etc/systemd/system")
    src = _sync.files_dir(tree) / "systemd" / "demo.service"
    dest = ctx.dest("/etc/systemd/system/demo.service")
    dest.parent.mkdir(parents=True)
    dest.write_text("old")
    dest.chmod(0o000)
    ctx.dry_run = True
    try:
        assert _sync.install_file(ctx, entry, src) is True
    finally:
        dest.chmod(0o644)
    assert ctx.failures == 0


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


def test_append_redis_includes_noop_does_not_rewrite(ctx):
    redis = ctx.dest("/etc/redis")
    redis.mkdir(parents=True)
    conf = redis / "redis.conf"
    conf.write_text("bind 127.0.0.1\n")
    _sync.append_redis_includes(ctx)
    before = conf.stat().st_mtime_ns
    time.sleep(0.01)
    _sync.append_redis_includes(ctx)
    assert conf.stat().st_mtime_ns == before


@pytest.mark.skipif(os.geteuid() == 0, reason="root bypasses file perms")
def test_append_redis_includes_dry_run_survives_unreadable_conf(ctx):
    redis = ctx.dest("/etc/redis")
    redis.mkdir(parents=True)
    conf = redis / "redis.conf"
    conf.write_text("bind 127.0.0.1\n")
    conf.chmod(0o000)
    ctx.dry_run = True
    try:
        _sync.append_redis_includes(ctx)
    finally:
        conf.chmod(0o644)
    assert ctx.failures == 0


@pytest.mark.skipif(os.geteuid() == 0, reason="root bypasses file perms")
def test_append_redis_includes_fails_cleanly_on_unreadable_conf(ctx):
    redis = ctx.dest("/etc/redis")
    redis.mkdir(parents=True)
    conf = redis / "redis.conf"
    conf.write_text("bind 127.0.0.1\n")
    conf.chmod(0o000)
    try:
        _sync.append_redis_includes(ctx)
    finally:
        conf.chmod(0o644)
    assert ctx.failures == 1


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


def _make_wheel_tar(tmp_path, release):
    src = tmp_path / "wh-src"
    src.mkdir()
    (src / "requirements.txt").write_text(
        f"somepkg==1.0\neigsep-field=={release} \\\n"
        "    --hash=sha256:deadbeef\n"
    )
    tar = tmp_path / "wheels-linux_aarch64.tar.xz"
    with tarfile.open(tar, "w:xz") as tf:
        for p in src.iterdir():
            tf.add(p, arcname=p.name)
    sha = hashlib.sha256(tar.read_bytes()).hexdigest()
    return tar, sha


def test_wheelhouse_pin_parses_appended_line(tmp_path):
    (tmp_path / "requirements.txt").write_text(
        "a==1\neigsep-field==2026.4.0 \\\n    --hash=sha256:ff\n"
    )
    assert _sync.wheelhouse_pin(tmp_path) == "2026.4.0"


def test_wheelhouse_skips_when_pin_matches(ctx, tmp_path, monkeypatch):
    wh = tmp_path / "wheels"
    wh.mkdir()
    (wh / "requirements.txt").write_text("eigsep-field==2026.4.0\n")
    monkeypatch.setattr(_sync, "WHEELHOUSE", wh)
    monkeypatch.setattr(_sync, "_installed_field_version", lambda: "2026.4.0")
    called = []
    monkeypatch.setattr(_sync, "_download", lambda *a: called.append(a))
    runs = []
    monkeypatch.setattr(_sync, "_run", lambda cmd, **kw: runs.append(cmd))
    _sync.step_wheelhouse(ctx)
    assert called == []
    assert runs == []
    assert ctx.failures == 0


def test_wheelhouse_reinstalls_when_venv_behind_pin(
    ctx, tmp_path, monkeypatch
):
    """A prior run swapped the wheelhouse but the pip install failed
    (or never ran): pin == release must not short-circuit forever."""
    wh = tmp_path / "wheels"
    wh.mkdir()
    (wh / "requirements.txt").write_text("eigsep-field==2026.4.0\n")
    monkeypatch.setattr(_sync, "WHEELHOUSE", wh)
    monkeypatch.setattr(_sync, "_installed_field_version", lambda: "2026.3.0")
    runs = []

    def fake_run(cmd, **kw):
        runs.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(_sync, "_run", fake_run)
    _sync.step_wheelhouse(ctx)
    pip = str(_sync.VENV_PATH / "bin" / "pip")
    assert any(c[:2] == [pip, "install"] and "-r" in c for c in runs)


def test_wheelhouse_reinstall_skipped_in_dry_run(ctx, tmp_path, monkeypatch):
    wh = tmp_path / "wheels"
    wh.mkdir()
    (wh / "requirements.txt").write_text("eigsep-field==2026.4.0\n")
    monkeypatch.setattr(_sync, "WHEELHOUSE", wh)
    monkeypatch.setattr(_sync, "_installed_field_version", lambda: "2026.3.0")
    runs = []
    monkeypatch.setattr(_sync, "_run", lambda cmd, **kw: runs.append(cmd))
    ctx.dry_run = True
    _sync.step_wheelhouse(ctx)
    assert runs == []


def test_wheelhouse_swap_and_pip(ctx, tmp_path, monkeypatch):
    tar, sha = _make_wheel_tar(tmp_path, "2026.4.0")
    wh = tmp_path / "opt" / "wheels"
    wh.mkdir(parents=True)
    (wh / "requirements.txt").write_text("eigsep-field==2026.3.0\n")
    monkeypatch.setattr(_sync, "WHEELHOUSE", wh)

    def fake_download(url, dest):
        if url.endswith(".sha256"):
            dest.write_text(f"{sha}  wheels-linux_aarch64.tar.xz\n")
        else:
            dest.write_bytes(tar.read_bytes())

    monkeypatch.setattr(_sync, "_download", fake_download)
    runs = []

    def fake_run(cmd, **kw):
        runs.append(cmd)
        # git commands fail (fake tree has no tag) → the post-swap
        # tree reinstall must trigger; everything else succeeds.
        rc = 1 if cmd[0] == "git" else 0
        return subprocess.CompletedProcess(cmd, rc, "", "")

    monkeypatch.setattr(_sync, "_run", fake_run)
    _sync.step_wheelhouse(ctx)
    assert _sync.wheelhouse_pin(wh) == "2026.4.0"
    assert (wh.parent / "wheels.prev" / "requirements.txt").exists()
    assert (wh.parent / "previous-release").read_text() == "2026.3.0"
    pip = str(_sync.VENV_PATH / "bin" / "pip")
    assert any(c[:2] == [pip, "install"] and "-r" in c for c in runs)
    assert [pip, "install", "--quiet", str(ctx.tree)] in runs


def test_wheelhouse_sha_mismatch_keeps_old(ctx, tmp_path, monkeypatch):
    tar, _ = _make_wheel_tar(tmp_path, "2026.4.0")
    wh = tmp_path / "opt" / "wheels"
    wh.mkdir(parents=True)
    (wh / "requirements.txt").write_text("eigsep-field==2026.3.0\n")
    monkeypatch.setattr(_sync, "WHEELHOUSE", wh)

    def fake_download(url, dest):
        if url.endswith(".sha256"):
            dest.write_text("0" * 64 + "  wheels-linux_aarch64.tar.xz\n")
        else:
            dest.write_bytes(tar.read_bytes())

    monkeypatch.setattr(_sync, "_download", fake_download)
    _sync.step_wheelhouse(ctx)
    assert ctx.failures == 1
    assert _sync.wheelhouse_pin(wh) == "2026.3.0"


def test_wheelhouse_404_warns_and_skips(ctx, tmp_path, monkeypatch):
    import urllib.error

    wh = tmp_path / "wheels"
    wh.mkdir()
    (wh / "requirements.txt").write_text("eigsep-field==2026.3.0\n")
    monkeypatch.setattr(_sync, "WHEELHOUSE", wh)

    def fake_download(url, dest):
        raise urllib.error.HTTPError(url, 404, "nf", {}, None)

    monkeypatch.setattr(_sync, "_download", fake_download)
    _sync.step_wheelhouse(ctx)
    assert ctx.failures == 0  # mid-cycle: warn, not fail
    assert _sync.wheelhouse_pin(wh) == "2026.3.0"


@pytest.fixture
def panda_ctx(ctx):
    role = ctx.dest("/etc/eigsep/role")
    role.parent.mkdir(parents=True, exist_ok=True)
    role.write_text("role = panda\n")
    ctx.manifest["firmware"] = {
        "pico": {
            "asset": "pico_multi.uf2",
            "source": "https://github.com/EIGSEP/pico-firmware",
            "tag": "v4.1.0",
            "sha256": "",
            "roles": ["panda"],
        },
        "rfsoc": {
            "asset": "rfsoc_2026.tar.gz",
            "source": "https://github.com/EIGSEP/eigsep_dac",
            "tag": "v0.3.0",
            "sha256": "",
            "roles": ["backend"],
        },
    }
    return ctx


def test_firmware_downloads_missing_blob(panda_ctx, monkeypatch):
    got = []

    def fake_download(url, dest):
        got.append(url)
        dest.write_bytes(b"UF2")

    monkeypatch.setattr(_sync, "_download", fake_download)
    _sync.step_firmware(panda_ctx)
    blessed = panda_ctx.dest("/opt/eigsep/firmware/pico/pico_multi.uf2")
    assert blessed.read_bytes() == b"UF2"
    assert got == [
        "https://github.com/EIGSEP/pico-firmware"
        "/releases/download/v4.1.0/pico_multi.uf2"
    ]  # rfsoc is backend-only: not fetched on panda


def test_firmware_present_no_pin_is_kept(panda_ctx, monkeypatch):
    blessed = panda_ctx.dest("/opt/eigsep/firmware/pico/pico_multi.uf2")
    blessed.parent.mkdir(parents=True)
    blessed.write_bytes(b"OLD")
    (blessed.parent / "pico_multi.uf2.tag").write_text("v4.1.0\n")
    monkeypatch.setattr(
        _sync,
        "_download",
        lambda *a: pytest.fail("must not download"),
    )
    _sync.step_firmware(panda_ctx)
    assert blessed.read_bytes() == b"OLD"


def test_firmware_tag_bump_refetches(panda_ctx, monkeypatch):
    """sha256 == "" (a stable asset name) means the tag marker is the
    only staleness signal; a bumped [firmware.*].tag must refresh the
    blob even though the blob itself is present."""
    blessed = panda_ctx.dest("/opt/eigsep/firmware/pico/pico_multi.uf2")
    blessed.parent.mkdir(parents=True)
    blessed.write_bytes(b"OLD")
    (blessed.parent / "pico_multi.uf2.tag").write_text("v4.0.0\n")
    got = []

    def fake_download(url, dest):
        got.append(url)
        dest.write_bytes(b"NEW")

    monkeypatch.setattr(_sync, "_download", fake_download)
    _sync.step_firmware(panda_ctx)
    assert blessed.read_bytes() == b"NEW"
    assert got == [
        "https://github.com/EIGSEP/pico-firmware"
        "/releases/download/v4.1.0/pico_multi.uf2"
    ]
    marker = (blessed.parent / "pico_multi.uf2.tag").read_text().strip()
    assert marker == "v4.1.0"


def test_firmware_missing_tag_marker_counts_as_stale(panda_ctx, monkeypatch):
    """No marker at all (first sync after this feature lands) refetches
    once; that's intended — we're online."""
    blessed = panda_ctx.dest("/opt/eigsep/firmware/pico/pico_multi.uf2")
    blessed.parent.mkdir(parents=True)
    blessed.write_bytes(b"OLD")
    monkeypatch.setattr(
        _sync, "_download", lambda url, dest: dest.write_bytes(b"NEW")
    )
    _sync.step_firmware(panda_ctx)
    assert blessed.read_bytes() == b"NEW"
    marker = (blessed.parent / "pico_multi.uf2.tag").read_text().strip()
    assert marker == "v4.1.0"


def test_firmware_download_error_cleans_partial_tmp(panda_ctx, monkeypatch):
    import urllib.error

    def fake_download(url, dest):
        dest.write_bytes(b"PARTIAL")
        raise urllib.error.URLError("boom")

    monkeypatch.setattr(_sync, "_download", fake_download)
    _sync.step_firmware(panda_ctx)
    tmp = panda_ctx.dest("/opt/eigsep/firmware/pico/pico_multi.uf2.sync-tmp")
    assert not tmp.exists()
    assert panda_ctx.failures == 1


def test_firmware_sha_mismatch_refetches(panda_ctx, monkeypatch):
    import hashlib as h

    panda_ctx.manifest["firmware"]["pico"]["sha256"] = h.sha256(
        b"NEW"
    ).hexdigest()
    blessed = panda_ctx.dest("/opt/eigsep/firmware/pico/pico_multi.uf2")
    blessed.parent.mkdir(parents=True)
    blessed.write_bytes(b"OLD")
    monkeypatch.setattr(
        _sync, "_download", lambda url, dest: dest.write_bytes(b"NEW")
    )
    _sync.step_firmware(panda_ctx)
    assert blessed.read_bytes() == b"NEW"


def test_external_installs_when_binary_missing(panda_ctx, monkeypatch):
    panda_ctx.manifest["external"] = {
        "cmtvna": {
            "install_path": "/opt/eigsep/cmt-vna",
            "binary": "bin/cmtvna",
            "roles": ["panda"],
        }
    }
    script = panda_ctx.tree / "scripts" / "install-cmtvna.sh"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text("#!/bin/bash\n")
    runs = []
    monkeypatch.setattr(
        _sync,
        "_run",
        lambda cmd, **kw: (
            runs.append(cmd),
            subprocess.CompletedProcess(cmd, 0),
        )[1],
    )
    _sync.step_external(panda_ctx)
    assert runs and runs[0][0] == "bash"
    assert runs[0][1].endswith("install-cmtvna.sh")


def _git(*args, cwd):
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        env={
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t",
            "PATH": "/usr/bin:/bin",
            "HOME": str(cwd),
        },
    )


def test_sources_refreshes_blessed_marker(ctx, tmp_path, monkeypatch):
    # upstream repo with two tags
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    _git("init", "-q", cwd=upstream)
    (upstream / "f").write_text("1")
    _git("add", "f", cwd=upstream)
    _git("commit", "-qm", "one", cwd=upstream)
    _git("tag", "v1.0.0", cwd=upstream)
    (upstream / "f").write_text("2")
    _git("commit", "-aqm", "two", cwd=upstream)
    _git("tag", "v2.0.0", cwd=upstream)

    src_root = tmp_path / "src"
    src_root.mkdir()
    subprocess.run(
        ["git", "clone", "-q", "-b", "v1.0.0", str(upstream), "demo"],
        cwd=src_root,
        check=True,
        capture_output=True,
    )
    old = "0" * 40
    (src_root / "demo" / ".eigsep-blessed-commit").write_text(old + "\n")
    monkeypatch.setattr(_sync, "SRC_ROOT", src_root)
    ctx.manifest["packages"] = {
        "demo": {
            "source": str(upstream),
            "tag": "v2.0.0",
            "version": "2.0.0",
        }
    }
    _sync.step_sources(ctx)
    marker = (src_root / "demo" / ".eigsep-blessed-commit").read_text().strip()
    v2 = subprocess.run(
        ["git", "rev-list", "-n1", "v2.0.0"],
        cwd=upstream,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert marker == v2


def test_sources_warns_on_fetch_failure(ctx, tmp_path, monkeypatch, capsys):
    # upstream repo with one tag, already resolvable locally
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    _git("init", "-q", cwd=upstream)
    (upstream / "f").write_text("1")
    _git("add", "f", cwd=upstream)
    _git("commit", "-qm", "one", cwd=upstream)
    _git("tag", "v1.0.0", cwd=upstream)

    src_root = tmp_path / "src"
    src_root.mkdir()
    subprocess.run(
        ["git", "clone", "-q", "-b", "v1.0.0", str(upstream), "demo"],
        cwd=src_root,
        check=True,
        capture_output=True,
    )
    v1 = subprocess.run(
        ["git", "rev-list", "-n1", "v1.0.0"],
        cwd=upstream,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    old = "0" * 40
    (src_root / "demo" / ".eigsep-blessed-commit").write_text(old + "\n")
    monkeypatch.setattr(_sync, "SRC_ROOT", src_root)
    ctx.manifest["packages"] = {
        "demo": {
            "source": str(upstream),
            "tag": "v1.0.0",
            "version": "1.0.0",
        }
    }

    # kill upstream so `git fetch` in the clone can't reach it
    shutil.rmtree(upstream)

    _sync.step_sources(ctx)

    marker = (src_root / "demo" / ".eigsep-blessed-commit").read_text().strip()
    assert ctx.failures == 0
    assert marker == v1
    out = capsys.readouterr().out
    assert "warn" in out
    assert "fetch failed" in out


def test_sources_clone_uses_tree_manifest(ctx, tmp_path, monkeypatch):
    src_root = tmp_path / "src"
    src_root.mkdir()
    monkeypatch.setattr(_sync, "SRC_ROOT", src_root)
    ctx.manifest["packages"] = {
        "demo": {
            "source": "https://example.invalid/demo.git",
            "tag": "v1.0.0",
            "version": "1.0.0",
        }
    }

    from eigsep_field import _image_install

    calls = []

    def fake_clone_sources(args, manifest=None):
        calls.append(manifest)
        return 0

    monkeypatch.setattr(
        _image_install, "_cmd_clone_sources", fake_clone_sources
    )

    _sync.step_sources(ctx)

    assert calls == [ctx.manifest]


def test_read_apt_packages_skips_comments(tree):
    f = _sync.files_dir(tree) / "apt-packages.txt"
    f.write_text("# c\n\npython3\nchrony\n")
    assert _sync.read_apt_packages(tree) == ["python3", "chrony"]


def test_step_files_tracks_units_and_restarts(ctx, tree):
    f = _sync.files_dir(tree)
    (f / "dhcp").mkdir()
    (f / "dhcp" / "dhcpd.conf").write_text("subnet {}\n")
    (f / "dhcp" / "isc-dhcp-server").write_text("INTERFACESv4=eth0\n")
    # redis.conf must exist for the include-append
    rc = ctx.dest("/etc/redis/redis.conf")
    rc.parent.mkdir(parents=True)
    rc.write_text("bind 0.0.0.0\n")
    (f / "redis").mkdir()
    for n in ("eigsep.conf", "ephemeral.conf", "persistent.conf"):
        (f / "redis" / n).write_text(f"# {n}\n")
    (f / "chrony").mkdir()
    (f / "chrony" / "client.conf").write_text("server x\n")
    (f / "etc-eigsep").mkdir()
    (f / "etc-eigsep" / "uv.toml").write_text("[pip]\n")
    (f / "etc-eigsep" / "motd").write_text("r {{release}}\n")
    (f / "etc-profile-d").mkdir()
    (f / "etc-profile-d" / "eigsep.sh").write_text("export A=1\n")
    (f / "sudoers.d").mkdir()
    (f / "sudoers.d" / "eigsep-field").write_text("eigsep ALL=x\n")
    (f / "CHEATSHEET.md").write_text("# {{release}}\n")
    import unittest.mock as mock

    with mock.patch.object(_sync, "_sudoers_ok", return_value=True):
        _sync.step_files(ctx)
    assert "demo.service" in ctx.changed_units
    assert "chrony-wait.service" in ctx.changed_units
    assert "isc-dhcp-server.service" in ctx.restart_units
    assert ctx.dest("/etc/eigsep/manifest.toml").exists()


def test_step_dirs_skips_symlink_already_correct(ctx):
    home = ctx.dest("/home/eigsep")
    home.mkdir(parents=True)
    target = ctx.dest("/opt/eigsep/src")
    target.mkdir(parents=True)
    link = home / "src"
    link.symlink_to(target)
    before_ino = link.lstat().st_ino
    _sync.step_dirs(ctx)
    assert link.is_symlink()
    assert link.lstat().st_ino == before_ino
    assert ctx.failures == 0


def test_step_dirs_refuses_real_directory_at_link_path(ctx):
    home = ctx.dest("/home/eigsep")
    home.mkdir(parents=True)
    real_dir = home / "src"
    real_dir.mkdir()
    (real_dir / "keepme").write_text("x")
    _sync.step_dirs(ctx)
    assert real_dir.is_dir() and not real_dir.is_symlink()
    assert (real_dir / "keepme").exists()
    assert ctx.failures == 1


def test_step_systemd_passes_tree_manifest(ctx, fake_systemctl):
    import unittest.mock as mock

    from eigsep_field import _image_install

    calls = []

    def fake_enable_always(_, manifest=None):
        calls.append(manifest)
        return 0

    with mock.patch.object(
        _image_install, "_cmd_enable_always", fake_enable_always
    ):
        _sync.step_systemd(ctx)
    assert calls == [ctx.manifest]


def test_run_sync_dry_run_smoke_on_real_repo(capsys):
    import argparse

    args = argparse.Namespace(
        src=str(REPO),
        root="/",
        dry_run=True,
        skip=None,
        only=["files", "removals"],
    )
    rc = _sync.run_sync(args)
    out = capsys.readouterr().out
    assert "files" in out
    assert rc == 0 or rc == 1  # dev box may lack /etc/redis


def test_run_sync_only_and_skip_selection():
    sel = _sync.select_steps(only=["files", "verify"], skip=["verify"])
    assert sel == ["files"]
    assert _sync.select_steps(only=None, skip=None) == list(_sync.STEP_ORDER)


def test_run_sync_isolates_step_crash(monkeypatch, capsys):
    import argparse

    def boom(_ctx):
        raise RuntimeError("kaboom")

    monkeypatch.setitem(_sync.STEPS, "verify", boom)
    args = argparse.Namespace(
        src=str(REPO), root="/", dry_run=True, skip=None, only=["verify"]
    )
    rc = _sync.run_sync(args)
    captured = capsys.readouterr()
    assert rc == 1
    assert "verify: step crashed: kaboom" in captured.err
    assert "sync-image: 1 failure(s)" in captured.out


def test_run_sync_refuses_nonroot_path_outside_dry_run(
    tmp_path, monkeypatch, capsys
):
    import argparse

    # Simulate a real root run so the assertion targets the new --root
    # guard specifically, not the pre-existing euid check (both return
    # 2, but for different reasons).
    monkeypatch.setattr(_sync.os, "geteuid", lambda: 0)
    args = argparse.Namespace(
        src=str(REPO),
        root=str(tmp_path / "fake-root"),
        dry_run=False,
        skip=None,
        only=["files"],
    )
    rc = _sync.run_sync(args)
    assert rc == 2
    assert "--root" in capsys.readouterr().err


def test_cli_wires_sync_image(monkeypatch):
    from eigsep_field import cli

    seen = {}
    monkeypatch.setattr(cli, "run_sync", lambda args: seen.setdefault("ok", 0))
    rc = cli.main(["sync-image", "--dry-run"])
    assert rc == 0
    assert seen == {"ok": 0}
