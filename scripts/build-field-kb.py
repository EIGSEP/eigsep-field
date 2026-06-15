"""Assemble the offline field-KB corpus for the AnythingLLM operator agent.

Gathers the curated operator KB (docs/field-kb, minus the anythingllm/
config), the interface ICDs (docs/interface), the operator runbooks
(docs/operator), and the source + doc trees of the blessed field-stack
siblings into a single folder ready to import into AnythingLLM. Stamps
CORPUS-MANIFEST.md with the release version, build date, and the
resolved git commit of each tree so the agent can report which release
the corpus matches.

Sibling trees are enumerated from manifest.toml (the same packages +
git-backed hardware entries the image build clones), so the corpus
tracks the blessed tuple. Run on a machine where the siblings are
checked out under --src-root (default: the repo's parent directory).
"""

from __future__ import annotations

import argparse  # noqa: F401
import datetime as dt  # noqa: F401
import fnmatch
import shutil
import subprocess  # noqa: F401
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from eigsep_field import load_manifest  # noqa: E402,F401


def read_ignore(path: Path) -> list[str]:
    """Return non-comment, non-blank glob patterns from a corpus.ignore."""
    out: list[str] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        out.append(line)
    return out


def path_is_ignored(relpath: str, patterns: list[str]) -> bool:
    """True if relpath matches any ignore pattern.

    A trailing-slash pattern (``build/``) matches that directory anywhere
    in the path. Other patterns are fnmatch-ed against the full relative
    path and against each individual path component (so ``*.img`` matches
    at any depth).
    """
    parts = Path(relpath).parts
    for pat in patterns:
        if pat.endswith("/"):
            stripped = pat.rstrip("/")
            if any(fnmatch.fnmatch(p, stripped) for p in parts):
                return True
            continue
        if fnmatch.fnmatch(relpath, pat):
            return True
        if any(fnmatch.fnmatch(p, pat) for p in parts):
            return True
    return False


def copy_filtered(src: Path, dst: Path, patterns: list[str]) -> int:
    """Copy src/ into dst/, skipping ignored paths. Returns files copied."""
    count = 0
    for f in sorted(src.rglob("*")):
        if not f.is_file():
            continue
        rel = f.relative_to(src).as_posix()
        if path_is_ignored(rel, patterns):
            continue
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, target)
        count += 1
    return count


@dataclass(frozen=True)
class SiblingSource:
    """A sibling tree to gather into the corpus.

    ``clone_dir`` is the on-disk repo root under --src-root; ``package_dir``
    is the Python project dir (clone_dir + package_path), used to keep the
    copy focused on code+docs and avoid vendored SDK/submodule bloat.
    """

    name: str
    clone_dir: Path
    package_dir: Path


def sibling_sources(manifest: dict, src_root: Path) -> list[SiblingSource]:
    """Enumerate git-backed siblings to gather, mirroring the image build.

    Includes every [packages.*] entry and every [hardware.*] entry that
    has a ``source`` (PyPI-sdist hardware entries like lgpio have no tree
    and are skipped).

    Assumes the sibling trees are already cloned under ``src_root`` with
    submodules initialized — this never clones. A missing clone_dir is
    handled (warned + skipped) by ``build``; an uninitialized submodule
    would just copy nothing for that subtree.
    """
    out: list[SiblingSource] = []
    entries: list[tuple[str, dict]] = []
    entries += list(manifest.get("packages", {}).items())
    entries += [
        (n, e)
        for n, e in manifest.get("hardware", {}).items()
        if "source" in e
    ]
    for name, entry in entries:
        clone_dir = src_root / entry.get("clone_path", name)
        sub = entry.get("package_path")
        package_dir = clone_dir / sub if sub else clone_dir
        out.append(SiblingSource(name, clone_dir, package_dir))
    return out
