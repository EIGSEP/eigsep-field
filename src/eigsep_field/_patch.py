"""Shared helpers for ``eigsep-field patch|revert|capture|src`` and the
editable/drift checks that ``doctor`` runs.

Pure helpers + thin process wrappers — no argparse here. Callers in
``cli.py`` handle argument parsing and exit codes.

Filesystem layout on the Pi (overridable via env for tests/dev):
    /opt/eigsep/venv          — system venv (VIRTUAL_ENV)
    /opt/eigsep/src/<name>    — sibling source trees (EIGSEP_SRC)
    /opt/eigsep/wheels        — offline wheelhouse
    /opt/eigsep/captures      — operator-written field diffs
    /opt/eigsep/src/eigsep-field — project root with uv.lock for revert
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path

from eigsep_field._services import (
    services_importing_package,
    systemctl,
)

SRC_ROOT = Path(os.environ.get("EIGSEP_SRC", "/opt/eigsep/src"))
VENV_PATH = Path(os.environ.get("VIRTUAL_ENV", "/opt/eigsep/venv"))
WHEELHOUSE = Path(os.environ.get("EIGSEP_WHEELS", "/opt/eigsep/wheels"))
UV_CONFIG = Path(os.environ.get("UV_CONFIG_FILE", "/etc/eigsep/uv.toml"))
CAPTURES_DIR = Path(os.environ.get("EIGSEP_CAPTURES", "/opt/eigsep/captures"))
EIGSEP_FIELD_PROJECT = SRC_ROOT / "eigsep-field"

BLESSED_COMMIT_FILE = ".eigsep-blessed-commit"


@dataclass(frozen=True)
class Sibling:
    """Resolved manifest reference for a sibling source tree."""

    name: str
    pypi_name: str
    version: str
    tag: str
    src_path: Path


def all_siblings(manifest: dict) -> list[Sibling]:
    """Every ``[packages.*]`` and ``[hardware.*]`` entry as a Sibling.

    eigsep-field itself is not returned: it's cloned for its lockfile
    but operators don't patch/revert it as a sibling.
    """
    out: list[Sibling] = []
    for name, entry in manifest.get("packages", {}).items():
        out.append(
            Sibling(
                name=name,
                pypi_name=entry.get("pypi", name),
                version=entry["version"],
                tag=entry["tag"],
                src_path=SRC_ROOT / name,
            )
        )
    for name, entry in manifest.get("hardware", {}).items():
        out.append(
            Sibling(
                name=name,
                pypi_name=name,
                version=entry["version"],
                tag=entry["tag"],
                src_path=SRC_ROOT / name,
            )
        )
    return out


def resolve_sibling(manifest: dict, name: str) -> Sibling | None:
    """Match a name against TOML keys, then PyPI names, then None."""
    siblings = all_siblings(manifest)
    for s in siblings:
        if s.name == name:
            return s
    for s in siblings:
        if s.pypi_name == name:
            return s
    return None


def list_sibling_names(manifest: dict) -> list[str]:
    return [s.name for s in all_siblings(manifest)]


def editable_source(pypi_name: str) -> Path | None:
    """Return the editable source directory, or None if installed normally.

    Reads PEP 610 ``direct_url.json`` from dist-info — present and with
    ``dir_info.editable = true`` exactly when ``pip/uv install -e`` was
    used.
    """
    try:
        dist = distribution(pypi_name)
    except PackageNotFoundError:
        return None
    raw = dist.read_text("direct_url.json")
    if not raw:
        return None
    try:
        info = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not (info.get("dir_info") or {}).get("editable"):
        return None
    url = info.get("url", "")
    if url.startswith("file://"):
        return Path(url[len("file://") :])
    return None


def _git(src_path: Path, *args: str) -> tuple[int, str]:
    if not (src_path / ".git").exists():
        return 1, f"{src_path} is not a git repository"
    r = subprocess.run(
        ["git", "-C", str(src_path), *args],
        capture_output=True,
        text=True,
    )
    if r.returncode == 0:
        return r.returncode, r.stdout
    err = r.stderr or ""
    out = r.stdout or ""
    if err and out:
        return r.returncode, f"{err.rstrip()}\n{out}"
    return r.returncode, err or out


def git_head(src_path: Path) -> str | None:
    rc, out = _git(src_path, "rev-parse", "HEAD")
    return out.strip() if rc == 0 else None


def blessed_commit(src_path: Path) -> str | None:
    f = src_path / BLESSED_COMMIT_FILE
    if not f.exists():
        return None
    return f.read_text().strip() or None


def dirty_count(src_path: Path) -> int | None:
    rc, out = _git(src_path, "status", "--porcelain")
    if rc != 0:
        return None
    return len([line for line in out.splitlines() if line])


def require_root(action: str) -> int | None:
    """Return an exit code if euid != 0; None otherwise."""
    if os.geteuid() == 0:
        return None
    print(
        f"`eigsep-field {action}` writes to {VENV_PATH}; rerun with sudo:\n"
        f"    sudo eigsep-field {action} ...",
        file=sys.stderr,
    )
    return 2


def _uv_bin() -> str:
    venv_uv = VENV_PATH / "bin" / "uv"
    if venv_uv.exists():
        return str(venv_uv)
    found = shutil.which("uv")
    if found:
        return found
    return "uv"


def run_uv(*args: str) -> int:
    env = os.environ.copy()
    env["VIRTUAL_ENV"] = str(VENV_PATH)
    env["UV_PROJECT_ENVIRONMENT"] = str(VENV_PATH)
    env["UV_CONFIG_FILE"] = str(UV_CONFIG)
    return subprocess.run([_uv_bin(), *args], env=env).returncode


def install_editable(sibling: Sibling) -> int:
    return run_uv(
        "pip",
        "install",
        "--no-deps",
        "--reinstall",
        "-e",
        str(sibling.src_path),
    )


def revert_all(project_dir: Path = EIGSEP_FIELD_PROJECT) -> int:
    return run_uv(
        "sync",
        "--frozen",
        "--offline",
        "--project",
        str(project_dir),
    )


def revert_package(sibling: Sibling) -> int:
    return run_uv(
        "pip",
        "install",
        "--no-deps",
        "--reinstall",
        "--force-reinstall",
        "--no-index",
        "--offline",
        "--find-links",
        str(WHEELHOUSE),
        f"{sibling.pypi_name}=={sibling.version}",
    )


def restart_units(units: list[str]) -> tuple[int, int]:
    """Run ``systemctl restart`` per unit; return (ok_count, fail_count)."""
    ok = failed = 0
    for unit in units:
        rc, msg = systemctl("restart", unit)
        if rc == 0:
            print(f"  restarted {unit}")
            ok += 1
        else:
            print(f"  FAIL restart {unit}: {msg}", file=sys.stderr)
            failed += 1
    return ok, failed


def build_capture(sibling: Sibling, manifest: dict) -> str | None:
    """Concatenate committed and uncommitted diffs against the blessed commit.

    Returns None when the tree has no .git/, no blessed-commit pin, or
    no diff against the baseline.
    """
    base = blessed_commit(sibling.src_path)
    if base is None:
        return None
    parts: list[str] = []
    rc, out = _git(sibling.src_path, "diff", f"{base}..HEAD")
    if rc == 0 and out:
        parts.append(out)
    rc, out = _git(sibling.src_path, "diff", "HEAD")
    if rc == 0 and out:
        parts.append(out)
    if not parts:
        return None

    head = git_head(sibling.src_path) or "?"
    try:
        hostname = subprocess.run(
            ["hostname"], capture_output=True, text=True, check=False
        ).stdout.strip()
    except FileNotFoundError:
        hostname = "?"
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    affected = services_importing_package(manifest, sibling.pypi_name)

    header = (
        "# eigsep-field capture\n"
        f"# release:    {manifest.get('release', '?')}\n"
        f"# sibling:    {sibling.name} "
        f"({sibling.pypi_name}=={sibling.version})\n"
        f"# blessed:    {base}\n"
        f"# head:       {head}\n"
        f"# hostname:   {hostname or '?'}\n"
        f"# captured:   {now}\n"
        f"# affected:   {', '.join(affected) or '(no services)'}\n"
        "#\n"
    )
    return header + "\n".join(parts)
