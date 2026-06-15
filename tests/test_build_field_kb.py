"""Tests for scripts/build-field-kb.py corpus assembly."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "build-field-kb.py"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "build_field_kb", SCRIPT_PATH
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("build_field_kb", mod)
    spec.loader.exec_module(mod)
    return mod


def test_read_ignore_skips_comments_and_blanks(tmp_path):
    m = _load_module()
    f = tmp_path / "corpus.ignore"
    f.write_text("# comment\n\n.git/\n*.img\n")
    assert m.read_ignore(f) == [".git/", "*.img"]


def test_path_is_ignored_matches_dir_and_glob():
    m = _load_module()
    pats = [".git/", "*.img", "build/", "*.egg-info/"]
    assert m.path_is_ignored("a/.git/config", pats)
    assert m.path_is_ignored("x/y/foo.img", pats)
    assert m.path_is_ignored("pkg/build/lib.py", pats)
    assert m.path_is_ignored("src/eigsep_field.egg-info/SOURCES.txt", pats)
    assert not m.path_is_ignored("src/eigsep/io.py", pats)
    assert not m.path_is_ignored("docs/cmt.pdf", pats)


def test_copy_filtered_excludes_ignored(tmp_path):
    m = _load_module()
    src = tmp_path / "src"
    (src / ".git").mkdir(parents=True)
    (src / ".git" / "x").write_text("nope")
    (src / "pkg").mkdir()
    (src / "pkg" / "io.py").write_text("keep")
    (src / "big.img").write_text("nope")
    dst = tmp_path / "dst"
    n = m.copy_filtered(src, dst, [".git/", "*.img"])
    assert (dst / "pkg" / "io.py").read_text() == "keep"
    assert not (dst / ".git").exists()
    assert not (dst / "big.img").exists()
    assert n == 1


def test_sibling_sources_from_manifest(tmp_path):
    m = _load_module()
    manifest = {
        "packages": {
            "eigsep_redis": {
                "source": "https://x/eigsep_redis", "tag": "v2.3.0",
            },
            "picohost": {
                "source": "https://x/pico-firmware", "tag": "v3.6.0",
                "clone_path": "pico-firmware", "package_path": "picohost",
            },
        },
        "hardware": {
            "casperfpga": {
                "source": "https://x/casperfpga", "tag": "v0.7.2",
            },
            "lgpio": {"version": "0.2.2.0"},  # no source -> skipped
        },
    }
    src_root = tmp_path
    srcs = m.sibling_sources(manifest, src_root)
    names = {s.name: s for s in srcs}
    assert "lgpio" not in names              # PyPI sdist, no tree
    assert names["eigsep_redis"].clone_dir == src_root / "eigsep_redis"
    # default branch: package_dir == clone_dir when no package_path set
    assert names["eigsep_redis"].package_dir == src_root / "eigsep_redis"
    assert names["picohost"].clone_dir == src_root / "pico-firmware"
    assert names["picohost"].package_dir == src_root / "pico-firmware" / "picohost"
    assert names["casperfpga"].clone_dir == src_root / "casperfpga"
