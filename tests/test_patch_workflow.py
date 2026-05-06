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
    assert "unknown sibling" in err


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
    names = [t[0] for t in targets]
    for pkg in manifest["packages"]:
        assert pkg in names
    for hw in manifest["hardware"]:
        assert hw in names
    # eigsep-field is staged from the runner's checkout in image.yml,
    # not cloned from upstream — see _image_install module docstring.
    assert "eigsep-field" not in names
