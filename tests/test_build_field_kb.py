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
