"""Tests for the field hot-patch workflow: services_importing helpers,
sibling resolution, capture-diff format, and CLI ``src`` lookup.

Pure-Python tests — no /opt/eigsep needed. Path constants in
``eigsep_field._patch`` are monkeypatched onto ``tmp_path`` per test.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = REPO_ROOT / "manifest.toml"


@pytest.fixture
def manifest() -> dict:
    return tomllib.loads(MANIFEST_PATH.read_text())


# ----- _services helpers -----


def test_services_importing_package_picohost(manifest):
    from eigsep_field._services import services_importing_package

    units = services_importing_package(manifest, "picohost")
    assert "picomanager.service" in units


def test_services_importing_package_eigsep_observing(manifest):
    from eigsep_field._services import services_importing_package

    units = services_importing_package(manifest, "eigsep_observing")
    assert "eigsep-observe.service" in units
    assert "eigsep-observe-writer.service" in units


def test_services_importing_package_no_service(manifest):
    """eigsep_redis and pyvalon import as libraries; no own units."""
    from eigsep_field._services import services_importing_package

    assert services_importing_package(manifest, "eigsep_redis") == []
    assert services_importing_package(manifest, "pyvalon") == []


def test_services_importing_package_unknown(manifest):
    from eigsep_field._services import services_importing_package

    assert services_importing_package(manifest, "not-a-package") == []


def test_services_importing_handles_only_sibling_kind(manifest):
    """``redis`` is kind=apt and must NOT be returned as importing anyone."""
    from eigsep_field._services import services_importing

    apt_only = [
        e["unit"]
        for e in manifest["services"].values()
        if e.get("kind") == "apt"
    ]
    for unit in apt_only:
        assert unit not in services_importing(manifest["services"], "v3.1.0")


# ----- _patch resolution + listing -----


def test_all_siblings_includes_packages_and_hardware(manifest):
    from eigsep_field._patch import all_siblings

    names = {s.name for s in all_siblings(manifest)}
    assert "eigsep_observing" in names
    assert "casperfpga" in names  # from [hardware.*]
    assert "eigsep-field" not in names  # self-clone is implicit


def test_resolve_sibling_by_toml_key(manifest):
    from eigsep_field._patch import resolve_sibling

    s = resolve_sibling(manifest, "eigsep_observing")
    assert s is not None
    assert s.pypi_name == "eigsep_observing"
    assert s.src_path.name == "eigsep_observing"


def test_resolve_sibling_by_pypi_name_fallback(manifest):
    """Manifest key for VNA is 'eigsep-vna' (and pypi is the same)."""
    from eigsep_field._patch import resolve_sibling

    s = resolve_sibling(manifest, "eigsep-vna")
    assert s is not None
    assert s.tag == manifest["packages"]["eigsep-vna"]["tag"]


def test_resolve_sibling_unknown(manifest):
    from eigsep_field._patch import resolve_sibling

    assert resolve_sibling(manifest, "no-such-thing") is None


# ----- git-backed helpers -----


def _git_init(path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "test@example.com"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "config", "user.name", "Test"], check=True
    )


def _git_commit(path: Path, msg: str) -> str:
    subprocess.run(["git", "-C", str(path), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(path), "commit", "-q", "-m", msg], check=True
    )
    return subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


@pytest.fixture
def fake_src(tmp_path, monkeypatch, manifest):
    """A SRC_ROOT with one fully-cloned sibling tree (eigsep_observing)."""
    if shutil.which("git") is None:
        pytest.skip("git not available")
    src_root = tmp_path / "src"
    src_root.mkdir()
    sibling_dir = src_root / "eigsep_observing"
    sibling_dir.mkdir()
    (sibling_dir / "README.md").write_text("hello\n")
    _git_init(sibling_dir)
    sha = _git_commit(sibling_dir, "initial")
    (sibling_dir / ".eigsep-blessed-commit").write_text(sha + "\n")
    # Mirror clone-sources: hide the marker from `git status`.
    exclude = sibling_dir / ".git" / "info" / "exclude"
    with exclude.open("a") as f:
        f.write(".eigsep-blessed-commit\n")

    monkeypatch.setattr("eigsep_field._patch.SRC_ROOT", src_root)
    return src_root


def test_blessed_and_head_match_clean_tree(fake_src, manifest):
    from eigsep_field._patch import (
        blessed_commit,
        dirty_count,
        git_head,
        resolve_sibling,
    )

    s = resolve_sibling(manifest, "eigsep_observing")
    assert git_head(s.src_path) == blessed_commit(s.src_path)
    assert dirty_count(s.src_path) == 0


def test_dirty_count_after_edit(fake_src, manifest):
    from eigsep_field._patch import dirty_count, resolve_sibling

    s = resolve_sibling(manifest, "eigsep_observing")
    (s.src_path / "README.md").write_text("hello\nedit\n")
    assert dirty_count(s.src_path) == 1


def test_drift_detected_after_new_commit(fake_src, manifest):
    from eigsep_field._patch import (
        blessed_commit,
        git_head,
        resolve_sibling,
    )

    s = resolve_sibling(manifest, "eigsep_observing")
    (s.src_path / "fix.py").write_text("# field fix\n")
    new_sha = _git_commit(s.src_path, "field fix")
    assert git_head(s.src_path) == new_sha
    assert blessed_commit(s.src_path) != new_sha


def test_build_capture_includes_metadata_and_diff(fake_src, manifest):
    from eigsep_field._patch import build_capture, resolve_sibling

    s = resolve_sibling(manifest, "eigsep_observing")
    (s.src_path / "fix.py").write_text("# field fix\n")
    _git_commit(s.src_path, "field fix")

    text = build_capture(s, manifest)
    assert text is not None
    assert "# eigsep-field capture" in text
    assert f"# release:    {manifest['release']}" in text
    assert "# sibling:    eigsep_observing" in text
    assert "# affected:   eigsep-observe.service" in text
    assert "fix.py" in text  # the actual diff payload


def test_build_capture_returns_none_on_clean_tree(fake_src, manifest):
    from eigsep_field._patch import build_capture, resolve_sibling

    s = resolve_sibling(manifest, "eigsep_observing")
    assert build_capture(s, manifest) is None


# ----- CLI src command -----


def test_cli_src_prints_path(fake_src, capsys, manifest):
    from eigsep_field.cli import main

    rc = main(["src", "eigsep_observing"])
    out = capsys.readouterr().out.strip()
    assert rc == 0
    assert out.endswith("/eigsep_observing")


def test_cli_src_unknown_sibling(capsys, manifest, tmp_path, monkeypatch):
    monkeypatch.setattr("eigsep_field._patch.SRC_ROOT", tmp_path)
    from eigsep_field.cli import main

    rc = main(["src", "definitely-not-a-sibling"])
    err = capsys.readouterr().err
    assert rc == 2
    assert "unknown target" in err


def test_cli_src_missing_tree(tmp_path, monkeypatch, capsys, manifest):
    """Resolving works but the directory hasn't been cloned yet."""
    monkeypatch.setattr("eigsep_field._patch.SRC_ROOT", tmp_path / "empty")
    (tmp_path / "empty").mkdir()
    from eigsep_field.cli import main

    rc = main(["src", "eigsep_observing"])
    err = capsys.readouterr().err
    assert rc == 2
    assert "no source tree" in err


# ----- _check_editable_drift -----


def test_doctor_drift_section_silent_on_clean_tree(fake_src, manifest):
    from eigsep_field.cli import _check_editable_drift

    notes = _check_editable_drift(manifest)
    # The fake tree exists for eigsep_observing only; no drift, no edit.
    drift_lines = [n for n in notes if "eigsep_observing" in n]
    assert drift_lines == []


def test_doctor_drift_section_flags_drift(fake_src, manifest):
    from eigsep_field.cli import _check_editable_drift

    s_dir = fake_src / "eigsep_observing"
    (s_dir / "fix.py").write_text("# field fix\n")
    _git_commit(s_dir, "field fix")
    notes = _check_editable_drift(manifest)
    line = next((n for n in notes if "eigsep_observing" in n), None)
    assert line is not None
    assert "drifted" in line
    assert "eigsep-observe.service" in line


def test_doctor_drift_section_flags_dirty(fake_src, manifest):
    from eigsep_field.cli import _check_editable_drift

    s_dir = fake_src / "eigsep_observing"
    (s_dir / "README.md").write_text("hello\nedit\n")
    notes = _check_editable_drift(manifest)
    line = next((n for n in notes if "eigsep_observing" in n), None)
    assert line is not None
    assert "dirty" in line


# ----- _image_install.clone-sources targets -----


def test_clone_targets_covers_siblings_not_self(manifest):
    sys.path.insert(0, str(REPO_ROOT / "src"))
    try:
        from eigsep_field._image_install import _clone_targets
    finally:
        sys.path.pop(0)
    targets = _clone_targets(manifest)
    names = [t.name for t in targets]
    for pkg in manifest["packages"]:
        assert pkg in names
    for hw in manifest["hardware"]:
        assert hw in names
    # eigsep-field is staged from the runner's checkout in image.yml,
    # not cloned from upstream — see _image_install module docstring.
    assert "eigsep-field" not in names


def test_clone_targets_honor_clone_path(manifest):
    sys.path.insert(0, str(REPO_ROOT / "src"))
    try:
        from eigsep_field._image_install import _clone_targets
    finally:
        sys.path.pop(0)
    targets = {t.name: t for t in _clone_targets(manifest)}
    # picohost lives in the pico-firmware repo; clone_path retargets the
    # on-disk directory so `cd ~/src/pico-firmware` matches the repo name.
    assert targets["picohost"].clone_path == "pico-firmware"
    assert targets["picohost"].recursive_submodules is True
    # Defaults: anything without clone_path/recursive_submodules is left alone.
    assert targets["eigsep_redis"].clone_path == "eigsep_redis"
    assert targets["eigsep_redis"].recursive_submodules is False


def test_picohost_sibling_src_path_uses_clone_path(manifest):
    from eigsep_field._patch import resolve_sibling

    s = resolve_sibling(manifest, "picohost")
    assert s is not None
    assert s.src_path.name == "pico-firmware"


# ----- Firmware patch flow -----


@pytest.fixture
def fake_firmware_env(tmp_path, monkeypatch, manifest):
    """Stand up a SRC_ROOT + FIRMWARE_ROOT + SYSTEMD_ETC_ROOT layout that
    matches what the patch/revert flow expects on a real Pi.
    """
    if shutil.which("git") is None:
        pytest.skip("git not available")
    src_root = tmp_path / "src"
    firmware_root = tmp_path / "firmware"
    systemd_root = tmp_path / "systemd"
    src_root.mkdir()
    (firmware_root / "pico").mkdir(parents=True)
    systemd_root.mkdir()

    # The clone, with a fake .git/ dir so the .git existence check passes.
    src_path = src_root / "pico-firmware"
    src_path.mkdir()
    _git_init(src_path)
    (src_path / "build.sh").write_text("#!/bin/bash\nexit 0\n")
    (src_path / "build.sh").chmod(0o755)
    _git_commit(src_path, "initial")

    # Blessed UF2 (revert needs it).
    (firmware_root / "pico" / "pico_multi.uf2").write_text("blessed-uf2\n")

    # Pre-existing unit file so _render_drop_in's ExecStart sniffer finds it.
    (systemd_root / "picomanager.service").write_text(
        "[Service]\n"
        "ExecStart=/opt/eigsep/venv/bin/pico-manager "
        "--config /etc/eigsep/pico_config.json "
        "--uf2 /opt/eigsep/firmware/pico/pico_multi.uf2\n"
    )

    monkeypatch.setattr("eigsep_field._patch.SRC_ROOT", src_root)
    monkeypatch.setattr("eigsep_field._patch.FIRMWARE_ROOT", firmware_root)
    monkeypatch.setattr("eigsep_field._patch.SYSTEMD_ETC_ROOT", systemd_root)
    return {
        "src": src_path,
        "firmware": firmware_root,
        "systemd": systemd_root,
    }


def test_resolve_firmware_target_pico(fake_firmware_env, manifest):
    from eigsep_field._patch import resolve_firmware_target

    t = resolve_firmware_target(manifest, "pico-firmware")
    assert t is not None
    assert t.kind == "pico"
    assert t.name == "pico-firmware"
    assert t.service_unit == "picomanager.service"
    assert t.field_uf2.name == "pico_multi.uf2"
    assert "pico-firmware" in str(t.field_uf2)
    assert t.blessed_uf2.exists()


def test_resolve_firmware_target_unknown(fake_firmware_env, manifest):
    from eigsep_field._patch import resolve_firmware_target

    assert resolve_firmware_target(manifest, "no-such-firmware") is None


def test_list_firmware_target_names(fake_firmware_env, manifest):
    from eigsep_field._patch import list_firmware_target_names

    assert "pico-firmware" in list_firmware_target_names(manifest)


def test_has_active_firmware_patch_default_false(fake_firmware_env, manifest):
    from eigsep_field._patch import (
        has_active_firmware_patch,
        resolve_firmware_target,
    )

    t = resolve_firmware_target(manifest, "pico-firmware")
    assert has_active_firmware_patch(t) is False


def _make_run_recorder(fake_firmware_env, *, build_rc=0, flash_rc=0):
    """Capture _run calls; the build call materializes the artifact."""
    calls: list[tuple[tuple[str, ...], dict]] = []

    def fake_run(cmd, **kw):
        calls.append((tuple(cmd), dict(kw)))
        # bash <build.sh> → emit the artifact so the patch flow's
        # post-build existence check passes.
        if len(cmd) >= 2 and cmd[0] == "bash" and cmd[1].endswith("build.sh"):
            artifact = fake_firmware_env["src"] / "build" / "pico_multi.uf2"
            artifact.parent.mkdir(exist_ok=True)
            artifact.write_text("field-uf2\n")
            return build_rc
        if cmd[0] == "flash-picos":
            return flash_rc
        return 0

    return calls, fake_run


def test_patch_firmware_happy_path(fake_firmware_env, monkeypatch, manifest):
    from eigsep_field import _patch as P

    calls, fake_run = _make_run_recorder(fake_firmware_env)
    monkeypatch.setattr(P, "_run", fake_run)
    monkeypatch.setattr(P, "systemctl", lambda *args: (0, ""))

    t = P.resolve_firmware_target(manifest, "pico-firmware")
    rc = P.patch_firmware(t)
    assert rc == 0

    # Build was run from src_path
    build_calls = [c for c in calls if c[0][0] == "bash"]
    assert len(build_calls) == 1
    assert build_calls[0][1]["cwd"] == str(fake_firmware_env["src"])

    # flash-picos pointed at the field UF2 (not blessed).
    flash_calls = [c for c in calls if c[0][0] == "flash-picos"]
    assert len(flash_calls) == 1
    assert flash_calls[0][0][2] == str(t.field_uf2)

    # Drop-in written, referencing the field UF2.
    assert t.drop_in_path.exists()
    body = t.drop_in_path.read_text()
    assert "ExecStart=\nExecStart=" in body
    assert str(t.field_uf2) in body
    assert "pico-manager" in body
    assert P.has_active_firmware_patch(t) is True


def test_patch_firmware_build_failure_leaves_service_alone(
    fake_firmware_env, monkeypatch, manifest
):
    from eigsep_field import _patch as P

    calls, fake_run = _make_run_recorder(fake_firmware_env, build_rc=2)
    monkeypatch.setattr(P, "_run", fake_run)
    sysctl_calls: list[tuple] = []

    def fake_sysctl(*args):
        sysctl_calls.append(args)
        return (0, "")

    monkeypatch.setattr(P, "systemctl", fake_sysctl)

    t = P.resolve_firmware_target(manifest, "pico-firmware")
    rc = P.patch_firmware(t)
    assert rc == 2
    # No flash, no systemctl interactions, no drop-in.
    assert all(c[0][0] != "flash-picos" for c in calls)
    assert sysctl_calls == []
    assert not t.drop_in_path.exists()


def test_patch_firmware_flash_failure_restarts_service_without_dropin(
    fake_firmware_env, monkeypatch, manifest
):
    from eigsep_field import _patch as P

    calls, fake_run = _make_run_recorder(fake_firmware_env, flash_rc=3)
    monkeypatch.setattr(P, "_run", fake_run)
    sysctl_calls: list[tuple] = []

    def fake_sysctl(*args):
        sysctl_calls.append(args)
        return (0, "")

    monkeypatch.setattr(P, "systemctl", fake_sysctl)

    t = P.resolve_firmware_target(manifest, "pico-firmware")
    rc = P.patch_firmware(t)
    assert rc == 3
    # Service was stopped before flash, then started after flash fail.
    assert ("stop", t.service_unit) in sysctl_calls
    assert ("start", t.service_unit) in sysctl_calls
    assert not t.drop_in_path.exists()


def test_revert_firmware_removes_dropin_and_reflashes_blessed(
    fake_firmware_env, monkeypatch, manifest
):
    from eigsep_field import _patch as P

    # Stand up an active patch first.
    t = P.resolve_firmware_target(manifest, "pico-firmware")
    t.drop_in_path.parent.mkdir(parents=True, exist_ok=True)
    t.drop_in_path.write_text("# stale override\n")

    calls: list[tuple[tuple[str, ...], dict]] = []

    def fake_run(cmd, **kw):
        calls.append((tuple(cmd), dict(kw)))
        return 0

    monkeypatch.setattr(P, "_run", fake_run)
    monkeypatch.setattr(P, "systemctl", lambda *args: (0, ""))

    rc = P.revert_firmware(t)
    assert rc == 0
    assert not t.drop_in_path.exists()
    flash = [c for c in calls if c[0][0] == "flash-picos"]
    assert len(flash) == 1
    assert flash[0][0][2] == str(t.blessed_uf2)


def test_revert_firmware_idempotent_when_no_dropin(
    fake_firmware_env, monkeypatch, manifest
):
    """revert with no prior patch still reflashes blessed (safe to retry)."""
    from eigsep_field import _patch as P

    calls: list[tuple[tuple[str, ...], dict]] = []
    monkeypatch.setattr(
        P, "_run", lambda cmd, **kw: calls.append((tuple(cmd), kw)) or 0
    )
    monkeypatch.setattr(P, "systemctl", lambda *args: (0, ""))

    t = P.resolve_firmware_target(manifest, "pico-firmware")
    rc = P.revert_firmware(t)
    assert rc == 0
    flash = [c for c in calls if c[0][0] == "flash-picos"]
    assert len(flash) == 1


def test_swap_uf2_path_basic():
    from eigsep_field._patch import _swap_uf2_path

    out = _swap_uf2_path(
        "/opt/eigsep/venv/bin/pico-manager --config /etc/x.json "
        "--uf2 /opt/eigsep/firmware/pico/pico_multi.uf2",
        Path("/opt/eigsep/src/pico-firmware/build/pico_multi.uf2"),
    )
    assert (
        out == "/opt/eigsep/venv/bin/pico-manager --config /etc/x.json "
        "--uf2 /opt/eigsep/src/pico-firmware/build/pico_multi.uf2"
    )


def test_swap_uf2_path_no_uf2_flag_falls_back():
    """Fallback when the unit file ExecStart is missing or has no --uf2."""
    from eigsep_field._patch import _swap_uf2_path

    out = _swap_uf2_path("", Path("/some/field.uf2"))
    assert out.startswith("/opt/eigsep/venv/bin/pico-manager")
    assert "--uf2 /some/field.uf2" in out


# ----- Doctor surfaces drop-in override -----


def test_doctor_firmware_patch_note_when_dropin_present(
    fake_firmware_env, manifest
):
    from eigsep_field._patch import resolve_firmware_target
    from eigsep_field.cli import _check_firmware_patches

    t = resolve_firmware_target(manifest, "pico-firmware")
    t.drop_in_path.parent.mkdir(parents=True, exist_ok=True)
    t.drop_in_path.write_text("[Service]\nExecStart=\nExecStart=foo\n")

    notes = _check_firmware_patches(manifest)
    assert any("field-patched UF2 active" in n for n in notes)
    assert any("pico-firmware" in n for n in notes)


def test_doctor_firmware_patch_silent_without_dropin(
    fake_firmware_env, manifest
):
    from eigsep_field.cli import _check_firmware_patches

    notes = _check_firmware_patches(manifest)
    assert notes == []


# ----- CLI src / capture: firmware target awareness -----


def test_cli_src_resolves_firmware_target(fake_firmware_env, capsys):
    """`eigsep-field src pico-firmware` prints the shared clone path."""
    from eigsep_field.cli import main

    rc = main(["src", "pico-firmware"])
    out = capsys.readouterr().out.strip()
    assert rc == 0
    assert out.endswith("/pico-firmware")


def test_cli_src_unknown_lists_firmware_targets(capsys, tmp_path, monkeypatch):
    """src accepts both — unknown error must list firmware targets too."""
    monkeypatch.setattr("eigsep_field._patch.SRC_ROOT", tmp_path)
    from eigsep_field.cli import main

    rc = main(["src", "nope-not-a-thing"])
    err = capsys.readouterr().err
    assert rc == 2
    assert "unknown target" in err
    assert "pico-firmware" in err


def test_cli_capture_firmware_target_hints_sibling(fake_firmware_env, capsys):
    """`capture pico-firmware` → redirect to the shared-tree sibling."""
    from eigsep_field.cli import main

    rc = main(["capture", "pico-firmware"])
    err = capsys.readouterr().err
    assert rc == 2
    assert "firmware target" in err
    assert "picohost" in err
    assert "eigsep-field capture picohost" in err


def test_cli_capture_unknown_omits_firmware_targets(
    capsys, tmp_path, monkeypatch
):
    """capture is siblings-only — unknown list must not advertise firmware."""
    monkeypatch.setattr("eigsep_field._patch.SRC_ROOT", tmp_path)
    from eigsep_field.cli import main

    rc = main(["capture", "nope-not-a-thing"])
    err = capsys.readouterr().err
    assert rc == 2
    assert "unknown target" in err
    assert "pico-firmware" not in err
