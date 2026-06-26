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
    """Resolved manifest reference for a sibling source tree.

    ``src_path`` is the clone root (where ``.git`` lives — used by
    capture/diff and the on-disk existence check). ``package_path`` is
    the directory containing ``pyproject.toml`` and is what gets passed
    to ``uv pip install -e``. For most siblings the two are identical;
    they diverge when ``package_path`` is set in the manifest, as on the
    picohost entry whose Python project sits at
    ``pico-firmware/picohost/`` while ``.git`` lives at the repo root.
    """

    name: str
    pypi_name: str
    version: str
    tag: str
    src_path: Path
    package_path: Path


def _sibling_paths(entry: dict, name: str) -> tuple[Path, Path]:
    src_path = SRC_ROOT / entry.get("clone_path", name)
    sub = entry.get("package_path")
    package_path = src_path / sub if sub else src_path
    return src_path, package_path


def all_siblings(manifest: dict) -> list[Sibling]:
    """Every ``[packages.*]`` and ``[hardware.*]`` entry as a Sibling.

    eigsep-field itself is not returned: it's cloned for its lockfile
    but operators don't patch/revert it as a sibling. ``clone_path`` on
    the manifest entry overrides the on-disk directory name — see the
    picohost entry which lives under ``pico-firmware/`` because that's
    the repo it shares with the C firmware source. ``package_path``
    further narrows to the subdir holding ``pyproject.toml`` when the
    Python package isn't at the repo root.
    """
    out: list[Sibling] = []
    for name, entry in manifest.get("packages", {}).items():
        src_path, package_path = _sibling_paths(entry, name)
        out.append(
            Sibling(
                name=name,
                pypi_name=entry.get("pypi", name),
                version=entry["version"],
                tag=entry["tag"],
                src_path=src_path,
                package_path=package_path,
            )
        )
    for name, entry in manifest.get("hardware", {}).items():
        if "source" not in entry:
            # PyPI-sdist hardware entries (e.g. lgpio) have no clone
            # on the image — nothing to patch/capture/revert.
            continue
        src_path, package_path = _sibling_paths(entry, name)
        out.append(
            Sibling(
                name=name,
                pypi_name=name,
                version=entry["version"],
                tag=entry["tag"],
                src_path=src_path,
                package_path=package_path,
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


# ---------------------------------------------------------------------------
# Firmware build targets — for [firmware.<kind>.build] entries that declare
# an on-image rebuild flow (currently just pico-firmware). Resolved by
# ``src_path`` (which equals the clone directory under SRC_ROOT and is what
# the operator types: ``eigsep-field patch pico-firmware``).
# ---------------------------------------------------------------------------


FIRMWARE_ROOT = Path(os.environ.get("EIGSEP_FIRMWARE", "/opt/eigsep/firmware"))
PATCH_MARKER_FILENAME = ".field-patch"


@dataclass(frozen=True)
class FirmwareTarget:
    """A firmware kind whose UF2 can be rebuilt + reflashed in the field.

    Carries everything the patch/revert flow needs without re-reading the
    manifest: the on-disk source path, the build script + artifact, the
    systemd unit that runs the firmware (informational — the patch flow
    no longer touches it), and the blessed UF2 path used as the revert
    target.
    """

    kind: str
    name: str
    src_path: Path
    script: str
    artifact_relpath: str
    service_unit: str
    blessed_uf2: Path

    @property
    def field_uf2(self) -> Path:
        return self.src_path / self.artifact_relpath

    @property
    def patch_marker(self) -> Path:
        """Sentinel recording that a field-built UF2 is currently flashed.

        Lives beside the blessed UF2 (never overwriting it). Its presence
        is what ``has_active_firmware_patch`` / ``doctor`` / ``revert``
        key off. Under the pico-firmware #128 model the patch flow no
        longer modifies the systemd unit, so there is no drop-in to serve
        as the marker — this file does instead.
        """
        return self.blessed_uf2.parent / PATCH_MARKER_FILENAME


def all_firmware_targets(manifest: dict) -> list[FirmwareTarget]:
    """Return one FirmwareTarget per [firmware.*] entry with a ``build`` block."""
    out: list[FirmwareTarget] = []
    for kind, entry in manifest.get("firmware", {}).items():
        build = entry.get("build")
        if not build:
            continue
        src_path = SRC_ROOT / build["src_path"]
        out.append(
            FirmwareTarget(
                kind=kind,
                name=build["src_path"],
                src_path=src_path,
                script=build["script"],
                artifact_relpath=build["artifact"],
                service_unit=build["service"],
                blessed_uf2=FIRMWARE_ROOT / kind / entry["asset"],
            )
        )
    return out


def resolve_firmware_target(
    manifest: dict, name: str
) -> FirmwareTarget | None:
    for t in all_firmware_targets(manifest):
        if t.name == name:
            return t
    return None


def list_firmware_target_names(manifest: dict) -> list[str]:
    return [t.name for t in all_firmware_targets(manifest)]


def _run(cmd: list[str], **kw) -> int:
    """Wrapper around subprocess.run that streams stdout/stderr."""
    return subprocess.run(cmd, **kw).returncode


def _flash_picos_bin() -> str | None:
    """Resolve the ``flash-picos`` console script.

    ``picohost`` installs it into ``VENV_PATH/bin/``, which is not on
    sudo's ``secure_path``. Hard-resolve the venv copy before falling
    back to PATH so ``sudo eigsep-field patch pico-firmware`` works
    without ``sudo -E`` gymnastics. Mirrors ``_uv_bin()``.

    Returns ``None`` when no resolvable binary exists, so callers can
    fail loudly *before* building or flashing. Returning the bare command
    name would cause ``subprocess.run`` to raise ``FileNotFoundError``
    mid-flow with a confusing message; an explicit ``None`` lets
    ``patch_firmware`` / ``revert_firmware`` print a clear "is picohost
    installed?" error instead.
    """
    venv_bin = VENV_PATH / "bin" / "flash-picos"
    if venv_bin.exists():
        return str(venv_bin)
    return shutil.which("flash-picos")


def patch_firmware(target: FirmwareTarget) -> int:
    """Build + reflash the field-built UF2 onto the pico(s).

    Order matters: build first (fails noisily before flashing anything),
    then flash against the **live** picomanager. The GPIO mass-BOOTSEL
    flash is electrical, so the manager rides it out and re-confirms the
    boards over Redis (it self-discovers; flash-picos is flash-only). The
    service is never stopped. A build failure leaves the pico(s)
    untouched; a flash failure leaves the previously-flashed firmware in
    place and writes no marker.
    """
    if not (target.src_path / ".git").exists():
        print(
            f"no source tree at {target.src_path} (or no .git/)",
            file=sys.stderr,
        )
        return 2
    script = target.src_path / target.script
    if not script.exists():
        print(f"build script {script} not found", file=sys.stderr)
        return 2
    flash_bin = _flash_picos_bin()
    if flash_bin is None:
        print(
            "flash-picos not found in venv or PATH; is picohost installed?",
            file=sys.stderr,
        )
        return 2

    print(f"building {target.name}: {script}")
    rc = _run(["bash", str(script)], cwd=str(target.src_path))
    if rc != 0:
        print(
            f"build failed (rc={rc}); pico(s) left untouched",
            file=sys.stderr,
        )
        return rc
    if not target.field_uf2.exists():
        print(
            f"build succeeded but {target.field_uf2} not produced",
            file=sys.stderr,
        )
        return 1

    print(f"flashing pico(s) with {target.field_uf2}")
    rc = _run([flash_bin, "--uf2", str(target.field_uf2)])
    if rc != 0:
        print(
            f"flash failed (rc={rc}); picomanager untouched",
            file=sys.stderr,
        )
        return rc

    marker = target.patch_marker
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(_render_patch_marker(target))
    print(f"wrote patch marker {marker}")
    return 0


def revert_firmware(target: FirmwareTarget) -> int:
    """Clear the patch marker and reflash the blessed UF2 onto the pico(s).

    Explicit reflash against the **live** picomanager — the manager no
    longer auto-flashes empty Redis, so reverting means flashing blessed
    ourselves. The service is never stopped; flash-picos confirms the
    boards via the manager-owned pico_config over Redis.
    """
    flash_bin = _flash_picos_bin()
    if flash_bin is None:
        print(
            "flash-picos not found in venv or PATH; is picohost installed?",
            file=sys.stderr,
        )
        return 2
    marker = target.patch_marker
    if marker.exists():
        marker.unlink()
        print(f"removed patch marker {marker}")
    else:
        print(f"no patch marker at {marker} (already reverted?)")

    if not target.blessed_uf2.exists():
        print(
            f"blessed UF2 {target.blessed_uf2} missing — cannot reflash",
            file=sys.stderr,
        )
        return 1
    print(f"flashing pico(s) with blessed {target.blessed_uf2}")
    rc = _run([flash_bin, "--uf2", str(target.blessed_uf2)])
    if rc != 0:
        print(f"flash failed (rc={rc})", file=sys.stderr)
        return rc
    print(f"  reflashed blessed {target.blessed_uf2}")
    return 0


def _render_patch_marker(target: FirmwareTarget) -> str:
    """Body of the patch marker recording which field UF2 is flashed.

    Plain ``key = value`` lines so an operator (or a future doctor
    enhancement) can read which UF2 is active and when it was applied.
    """
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return (
        "# eigsep-field firmware patch marker.\n"
        f"# Written by `eigsep-field patch {target.name}`.\n"
        f"# Remove with `eigsep-field revert {target.name}`.\n"
        f"field_uf2 = {target.field_uf2}\n"
        f"patched_at = {now}\n"
    )


def has_active_firmware_patch(target: FirmwareTarget) -> bool:
    """True if a patch marker exists for this target (field UF2 flashed)."""
    return target.patch_marker.exists()


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
    """Return an exit code if VENV_PATH is not writable; None otherwise.

    On a Pi, ``/opt/eigsep/venv`` is root-owned, so this check requires
    the operator to run with sudo (the documented workflow). On a dev
    box where ``VIRTUAL_ENV`` points at a user-owned venv, no sudo is
    required — same UX as ``pip install`` against the same venv.
    """
    if not VENV_PATH.exists():
        print(
            f"`eigsep-field {action}` expected a venv at {VENV_PATH} but "
            f"it does not exist. Set VIRTUAL_ENV to a real venv, or "
            f"install via the field image which provisions "
            f"/opt/eigsep/venv.",
            file=sys.stderr,
        )
        return 2
    if os.access(VENV_PATH, os.W_OK):
        return None
    print(
        f"`eigsep-field {action}` writes to {VENV_PATH} but it is not "
        f"writable by the current user; rerun with sudo:\n"
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
        str(sibling.package_path),
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
