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


def _fake_repo(tmp_path):
    """A minimal eigsep-field-shaped repo + one sibling under src_root."""
    repo = tmp_path / "eigsep-field"
    (repo / "docs" / "field-kb" / "anythingllm").mkdir(parents=True)
    (repo / "docs" / "field-kb" / "topology.md").write_text("# topo\n")
    (repo / "docs" / "field-kb" / "anythingllm" / "setup.md").write_text("x")
    (repo / "docs" / "field-kb" / "anythingllm" / "corpus.ignore").write_text(
        "*.img\n"
    )
    (repo / "docs" / "interface").mkdir(parents=True)
    (repo / "docs" / "interface" / "redis-keys.md").write_text("# keys\n")
    (repo / "docs" / "operator").mkdir(parents=True)
    (repo / "docs" / "operator" / "laptop.md").write_text("# laptop\n")
    (repo / "src").mkdir()
    (repo / "src" / "ef.py").write_text("# code\n")
    (repo / "firmware").mkdir()
    (repo / "firmware" / "loader.py").write_text("# rfsoc\n")
    (repo / "README.md").write_text("# eigsep-field\n")
    # a sibling next to the repo
    sib = tmp_path / "eigsep_redis"
    (sib / "src").mkdir(parents=True)
    (sib / "src" / "r.py").write_text("# redis\n")
    (sib / "big.img").write_text("BLOB")
    return repo


def test_build_assembles_corpus_and_stamp(tmp_path):
    m = _load_module()
    repo = _fake_repo(tmp_path)
    manifest = {
        "release": "2026.4.0",
        "packages": {
            "eigsep_redis": {"source": "https://x", "tag": "v2.3.0"}
        },
    }
    out = tmp_path / "corpus"
    m.build(
        manifest=manifest,
        repo_root=repo,
        src_root=tmp_path,
        out_dir=out,
        patterns=[".git/", "*.img"],
        build_date="2026-06-15",
    )
    # curated KB copied, anythingllm/ config excluded from the corpus
    assert (out / "kb" / "topology.md").exists()
    assert not (out / "kb" / "anythingllm" / "setup.md").exists()
    # ICDs + operator docs copied
    assert (out / "interface" / "redis-keys.md").exists()
    assert (out / "operator" / "laptop.md").exists()
    # this repo's code + firmware copied under repos/eigsep-field
    assert (out / "repos" / "eigsep-field" / "src" / "ef.py").exists()
    assert (out / "repos" / "eigsep-field" / "firmware" / "loader.py").exists()
    # sibling copied, blob excluded
    assert (out / "repos" / "eigsep_redis" / "src" / "r.py").exists()
    assert not (out / "repos" / "eigsep_redis" / "big.img").exists()
    # stamp present and names the release
    stamp = (out / "CORPUS-MANIFEST.md").read_text()
    assert "2026.4.0" in stamp
    assert "2026-06-15" in stamp
    assert "eigsep_redis" in stamp


def test_build_package_path_sibling_pulls_docs_and_readme(tmp_path):
    m = _load_module()
    repo = tmp_path / "eigsep-field"
    (repo / "docs" / "field-kb").mkdir(parents=True)
    (repo / "docs" / "field-kb" / "topology.md").write_text("# t\n")
    (repo / "docs" / "interface").mkdir(parents=True)
    (repo / "docs" / "operator").mkdir(parents=True)
    # picohost-style sibling: python pkg under a subdir, docs + README at root
    clone = tmp_path / "pico-firmware"
    (clone / "picohost").mkdir(parents=True)
    (clone / "picohost" / "host.py").write_text("# host\n")
    (clone / "docs").mkdir()
    (clone / "docs" / "BNO.md").write_text("# datasheet\n")
    (clone / "README.md").write_text("# pico-firmware\n")
    manifest = {
        "release": "2026.4.0",
        "packages": {
            "picohost": {
                "source": "https://x", "tag": "v3.6.0",
                "clone_path": "pico-firmware", "package_path": "picohost",
            }
        },
    }
    out = tmp_path / "corpus"
    m.build(
        manifest=manifest, repo_root=repo, src_root=tmp_path,
        out_dir=out, patterns=[".git/"], build_date="2026-06-15",
    )
    dest = out / "repos" / "picohost"
    assert (dest / "host.py").read_text() == "# host\n"      # package_dir
    assert (dest / "docs" / "BNO.md").exists()                # clone-root docs/
    assert (dest / "README.md").exists()                      # clone-root README


def test_main_runs_end_to_end(tmp_path, monkeypatch):
    m = _load_module()
    repo = _fake_repo(tmp_path)
    monkeypatch.setattr(m, "REPO_ROOT", repo)
    monkeypatch.setattr(
        m, "load_manifest",
        lambda: {"release": "2026.4.0",
                 "packages": {"eigsep_redis": {"source": "x", "tag": "v2.3.0"}}},
    )
    monkeypatch.setattr(
        m, "IGNORE_FILE",
        repo / "docs" / "field-kb" / "anythingllm" / "corpus.ignore",
    )
    out = tmp_path / "corpus"
    rc = m.main(["--src-root", str(tmp_path), "--out", str(out)])
    assert rc == 0
    assert (out / "CORPUS-MANIFEST.md").exists()
