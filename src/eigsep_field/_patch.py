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
    but operators don't patch/revert it as a sibling. ``clone_path`` on
    the manifest entry overrides the on-disk directory name — see the
    picohost entry which lives under ``pico-firmware/`` because that's
    the repo it shares with the C firmware source.
    """
    out: list[Sibling] = []
    for name, entry in manifest.get("packages", {}).items():
        out.append(
            Sibling(
                name=name,
                pypi_name=entry.get("pypi", name),
                version=entry["version"],
                tag=entry["tag"],
                src_path=SRC_ROOT / entry.get("clone_path", name),
            )
        )
    for name, entry in manifest.get("hardware", {}).items():
        out.append(
            Sibling(
                name=name,
                pypi_name=name,
                version=entry["version"],
                tag=entry["tag"],
                src_path=SRC_ROOT / entry.get("clone_path", name),
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
SYSTEMD_ETC_ROOT = Path(
    os.environ.get("EIGSEP_SYSTEMD_ETC", "/etc/systemd/system")
)
DROP_IN_FILENAME = "eigsep-patch.conf"


@dataclass(frozen=True)
class FirmwareTarget:
    """A firmware kind whose UF2 can be rebuilt + reflashed in the field.

    Carries everything the patch/revert flow needs without re-reading the
    manifest: the on-disk source path, the build script + artifact, the
    systemd unit whose ``--uf2`` flag gets retargeted, and the blessed
    UF2 path used as the revert target.
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
    def drop_in_path(self) -> Path:
        return SYSTEMD_ETC_ROOT / f"{self.service_unit}.d" / DROP_IN_FILENAME


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


def patch_firmware(target: FirmwareTarget) -> int:
    """Build + reflash + drop-in retarget — the field hotfix flow.

    Order matters: build first (fails noisily before touching the
    running service), then stop, flash, drop-in, start. A build failure
    leaves picomanager untouched. A flash failure restarts the service
    on its blessed config without writing the drop-in.
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

    print(f"building {target.name}: {script}")
    rc = _run(["bash", str(script)], cwd=str(target.src_path))
    if rc != 0:
        print(
            f"build failed (rc={rc}); picomanager left untouched",
            file=sys.stderr,
        )
        return rc
    if not target.field_uf2.exists():
        print(
            f"build succeeded but {target.field_uf2} not produced",
            file=sys.stderr,
        )
        return 1

    print(f"stopping {target.service_unit}")
    rc, msg = systemctl("stop", target.service_unit)
    if rc != 0:
        print(f"  FAIL stop: {msg}", file=sys.stderr)
        return rc

    print(f"flashing pico(s) with {target.field_uf2}")
    rc = _run(["flash-picos", "--uf2", str(target.field_uf2)])
    if rc != 0:
        print(
            "flash failed; restarting service on blessed config",
            file=sys.stderr,
        )
        # Best-effort: restart service so the panda comes back. Drop-in
        # was never written, so this picks up the blessed --uf2.
        systemctl("start", target.service_unit)
        return rc

    drop_in = target.drop_in_path
    drop_in.parent.mkdir(parents=True, exist_ok=True)
    drop_in.write_text(_render_drop_in(target))
    print(f"wrote drop-in {drop_in}")

    rc, msg = systemctl("daemon-reload")
    if rc != 0:
        print(f"  FAIL daemon-reload: {msg}", file=sys.stderr)
        return rc
    rc, msg = systemctl("start", target.service_unit)
    if rc != 0:
        print(f"  FAIL start: {msg}", file=sys.stderr)
        return rc
    print(f"  started {target.service_unit} (running field UF2)")
    print()
    print(
        "  WARNING: field UF2 must keep picotool's USB stdio config "
        "enabled,\n"
        "  otherwise the next `flash-picos` cannot trigger BOOTSEL and "
        "the\n"
        "  device becomes unrecoverable without physical SD/button "
        "access."
    )
    return 0


def revert_firmware(target: FirmwareTarget) -> int:
    """Drop the override and reflash the blessed UF2 onto the pico(s).

    Explicit reflash (rather than relying on picomanager's empty-Redis
    auto-flash branch) — picomanager skips the flash branch when Redis
    already has the picos, which is the common case post-patch.
    """
    drop_in = target.drop_in_path
    if drop_in.exists():
        drop_in.unlink()
        print(f"removed drop-in {drop_in}")
        # Best-effort: also remove the .d dir if now empty so /etc stays
        # tidy. systemd doesn't care either way.
        try:
            drop_in.parent.rmdir()
        except OSError:
            pass
    else:
        print(f"no drop-in at {drop_in} (already reverted?)")

    rc, msg = systemctl("daemon-reload")
    if rc != 0:
        print(f"  warn: daemon-reload failed: {msg}", file=sys.stderr)
    rc, msg = systemctl("stop", target.service_unit)
    if rc != 0:
        print(f"  FAIL stop: {msg}", file=sys.stderr)
        return rc

    if not target.blessed_uf2.exists():
        print(
            f"blessed UF2 {target.blessed_uf2} missing — cannot reflash",
            file=sys.stderr,
        )
        systemctl("start", target.service_unit)
        return 1
    print(f"flashing pico(s) with blessed {target.blessed_uf2}")
    rc = _run(["flash-picos", "--uf2", str(target.blessed_uf2)])
    if rc != 0:
        print(
            f"flash failed (rc={rc}); starting service anyway",
            file=sys.stderr,
        )
        systemctl("start", target.service_unit)
        return rc
    rc, msg = systemctl("start", target.service_unit)
    if rc != 0:
        print(f"  FAIL start: {msg}", file=sys.stderr)
        return rc
    print(f"  started {target.service_unit} (running blessed UF2)")
    return 0


def _render_drop_in(target: FirmwareTarget) -> str:
    """ExecStart override pointing the service at the field-built UF2.

    Constructed by stripping the blessed UF2 path from the unit's
    ExecStart and substituting the field path. We read the actual
    ExecStart so we don't drift if upstream picohost grows new flags.
    """
    fragment = _read_unit_execstart(target.service_unit)
    new = _swap_uf2_path(fragment, target.field_uf2)
    return (
        "# Written by `eigsep-field patch " + target.name + "`.\n"
        "# Remove with `eigsep-field revert " + target.name + "`.\n"
        "[Service]\n"
        "ExecStart=\n"
        f"ExecStart={new}\n"
    )


def _read_unit_execstart(unit: str) -> str:
    """Return the ExecStart= argv from the blessed unit file.

    Reads /etc/systemd/system/<unit> directly so the override is
    rebuilt against the *blessed* command line, not any existing
    drop-in. Returns "" on a missing/unreadable unit, in which case
    callers fall back to a hardcoded picomanager ExecStart.
    """
    path = SYSTEMD_ETC_ROOT / unit
    if not path.exists():
        return ""
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if line.startswith("ExecStart="):
            return line.split("=", 1)[1].strip()
    return ""


def _swap_uf2_path(execstart: str, new_uf2: Path) -> str:
    """Return ``execstart`` with the ``--uf2 <path>`` argument retargeted.

    Conservative tokenizer: splits on whitespace, finds ``--uf2`` and
    replaces the next token. If ``--uf2`` isn't present or
    ``execstart`` is empty, returns a minimal fallback ExecStart that
    invokes pico-manager with just the new UF2 — works on a stock
    picomanager.service, fails loudly if upstream drifts.
    """
    tokens = execstart.split()
    if not tokens or "--uf2" not in tokens:
        # Fallback: assume the blessed argv layout. Picomanager's unit
        # file is the upstream-aligned ExecStart=/opt/eigsep/venv/bin/
        # pico-manager --config /etc/eigsep/pico_config.json --uf2 ...
        return (
            "/opt/eigsep/venv/bin/pico-manager "
            "--config /etc/eigsep/pico_config.json "
            f"--uf2 {new_uf2}"
        )
    i = tokens.index("--uf2")
    if i + 1 >= len(tokens):
        tokens.append(str(new_uf2))
    else:
        tokens[i + 1] = str(new_uf2)
    return " ".join(tokens)


def has_active_firmware_patch(target: FirmwareTarget) -> bool:
    """True if a drop-in exists for this target's service."""
    return target.drop_in_path.exists()


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
