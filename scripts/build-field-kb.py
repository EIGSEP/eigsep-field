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

import argparse
import datetime as dt
import fnmatch
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from eigsep_field import load_manifest  # noqa: E402


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


IGNORE_FILE = REPO_ROOT / "docs" / "field-kb" / "anythingllm" / "corpus.ignore"


def git_commit(path: Path) -> str | None:
    """Best-effort short commit of a checked-out tree (None if not a repo)."""
    try:
        out = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, check=True,
        )
        return out.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def write_stamp(
    out_dir: Path, manifest: dict, commits: dict[str, str | None],
    build_date: str,
) -> None:
    lines = [
        "# CORPUS-MANIFEST",
        "",
        f"- release: {manifest.get('release', 'unknown')}",
        f"- built: {build_date}",
        "",
        "## Source trees",
        "",
        "| repo | commit |",
        "|------|--------|",
    ]
    for name in sorted(commits):
        lines.append(f"| {name} | {commits[name] or 'unknown'} |")
    (out_dir / "CORPUS-MANIFEST.md").write_text("\n".join(lines) + "\n")


def build(
    *, manifest: dict, repo_root: Path, src_root: Path, out_dir: Path,
    patterns: list[str], build_date: str,
) -> None:
    """Assemble the corpus folder at out_dir."""
    # out_dir is regenerated fresh each run — it is wiped first. Pass an
    # --out you are happy to have replaced (default: out/field-kb-corpus).
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    # 1. curated KB (minus the anythingllm/ operator config)
    copy_filtered(
        repo_root / "docs" / "field-kb",
        out_dir / "kb",
        patterns + ["anythingllm/"],
    )
    # 2. interface ICDs + operator docs
    copy_filtered(repo_root / "docs" / "interface", out_dir / "interface", patterns)
    copy_filtered(repo_root / "docs" / "operator", out_dir / "operator", patterns)

    # 3. this repo's own code/firmware/readme (eigsep-field is in scope)
    ef = out_dir / "repos" / "eigsep-field"
    for sub in ("src", "firmware"):
        if (repo_root / sub).is_dir():
            copy_filtered(repo_root / sub, ef / sub, patterns)
    if (repo_root / "README.md").exists():
        ef.mkdir(parents=True, exist_ok=True)
        shutil.copy2(repo_root / "README.md", ef / "README.md")

    # 4. blessed field-stack siblings: package dir + docs/ + top-level md/rst
    commits: dict[str, str | None] = {"eigsep-field": git_commit(repo_root)}
    for s in sibling_sources(manifest, src_root):
        if not s.clone_dir.is_dir():
            print(f"  WARN missing sibling tree: {s.clone_dir}", file=sys.stderr)
            commits[s.name] = None
            continue
        dest = out_dir / "repos" / s.name
        if s.package_dir.is_dir():
            copy_filtered(s.package_dir, dest, patterns)
        # docs/ and top-level READMEs live at the clone root, not under a
        # package_path subdir — copy them explicitly. For siblings whose
        # package_dir == clone_dir this is an idempotent re-copy; for
        # package_path siblings (e.g. picohost) it is load-bearing.
        if (s.clone_dir / "docs").is_dir():
            copy_filtered(s.clone_dir / "docs", dest / "docs", patterns)
        for doc in sorted(s.clone_dir.glob("*.md")) + sorted(
            s.clone_dir.glob("*.rst")
        ):
            dest.mkdir(parents=True, exist_ok=True)
            shutil.copy2(doc, dest / doc.name)
        commits[s.name] = git_commit(s.clone_dir)

    # 5. provenance
    write_stamp(out_dir, manifest, commits, build_date)
    print(f"corpus written to {out_dir}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--src-root", default=str(REPO_ROOT.parent),
        help="dir holding the sibling checkouts (default: repo parent)",
    )
    ap.add_argument(
        "--out", default=str(REPO_ROOT / "out" / "field-kb-corpus"),
        help="output corpus directory",
    )
    ap.add_argument(
        "--from-worktree", action="store_true",
        help="build from local checkouts as-is (default; reserved for "
             "future SHA-pinned mode)",
    )
    args = ap.parse_args(argv)
    build(
        manifest=load_manifest(),
        repo_root=REPO_ROOT,
        src_root=Path(args.src_root),
        out_dir=Path(args.out),
        patterns=read_ignore(IGNORE_FILE),
        build_date=dt.date.today().isoformat(),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
