"""In-place image sync (``eigsep-field sync-image``).

Pre-deployment, ONLINE tool: brings a flashed Pi up to the state of
the checked-out /opt/eigsep/src/eigsep-field tree. Mirrors what the
image stage (00-run.sh + _chroot-install.sh) installs; the drift test
tests/test_sync_map.py forces this mirror to stay complete. Offline
field mutations remain patch/revert/capture.

Every destination path resolves through ``SyncContext.dest`` so tests
can point ``root`` at a tmp_path. Spec:
docs/superpowers/specs/2026-07-07-sync-image-design.md
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from eigsep_field._services import systemctl  # noqa: F401 (later steps)

STAGE_REL = "image/pi-gen-config/stage-eigsep/00-eigsep-install"


def files_dir(tree: Path) -> Path:
    return tree / STAGE_REL / "files"


@dataclass(frozen=True)
class FileMapEntry:
    """One source-glob → destination-dir rule mirroring 00-run.sh.

    ``src`` is a glob relative to the stage files/ dir; a non-glob src
    that matches nothing is an error (the tree is broken).
    ``preserve_parent`` keeps the source's parent dir name under
    ``dest_dir`` (systemd drop-in dirs). ``unit`` names the systemd
    unit to ``try-reload-or-restart`` when the file changes.
    ``special``: "template" renders {{release}}/{{dev_banner}};
    "sudoers" gates the write on ``visudo -cf``.
    """

    src: str
    dest_dir: str
    mode: int = 0o644
    preserve_parent: bool = False
    unit: str | None = None
    special: str | None = None


FILE_MAP: tuple[FileMapEntry, ...] = (
    FileMapEntry("systemd/*.service", "/etc/systemd/system"),
    FileMapEntry("systemd/*.target", "/etc/systemd/system"),
    FileMapEntry(
        "systemd/*.service.d/*.conf",
        "/etc/systemd/system",
        preserve_parent=True,
    ),
    FileMapEntry(
        "systemd/*.target.d/*.conf",
        "/etc/systemd/system",
        preserve_parent=True,
    ),
    FileMapEntry("chrony/*.conf", "/etc/eigsep/chrony"),
    FileMapEntry(
        "dhcp/dhcpd.conf", "/etc/dhcp", unit="isc-dhcp-server.service"
    ),
    FileMapEntry(
        "dhcp/isc-dhcp-server",
        "/etc/default",
        unit="isc-dhcp-server.service",
    ),
    FileMapEntry(
        "redis/eigsep.conf",
        "/etc/redis/redis.conf.d",
        unit="redis-server.service",
    ),
    FileMapEntry("redis/ephemeral.conf", "/etc/eigsep/redis"),
    FileMapEntry("redis/persistent.conf", "/etc/eigsep/redis"),
    FileMapEntry("udev/*.rules", "/etc/udev/rules.d"),
    FileMapEntry("etc-eigsep/uv.toml", "/etc/eigsep"),
    FileMapEntry("etc-profile-d/eigsep.sh", "/etc/profile.d"),
    FileMapEntry(
        "sudoers.d/eigsep-field",
        "/etc/sudoers.d",
        mode=0o440,
        special="sudoers",
    ),
    FileMapEntry("etc-eigsep/motd", "/etc", special="template"),
    FileMapEntry("CHEATSHEET.md", "/opt/eigsep", special="template"),
)


@dataclass
class SyncContext:
    tree: Path
    manifest: dict
    root: Path = Path("/")
    dry_run: bool = False
    failures: int = 0
    changed_units: set[str] = field(default_factory=set)
    restart_units: set[str] = field(default_factory=set)

    def dest(self, absolute: str) -> Path:
        return self.root / absolute.lstrip("/")

    def note(self, msg: str) -> None:
        print(f"  {msg}")

    def fail(self, msg: str) -> None:
        self.failures += 1
        print(f"  FAIL: {msg}", file=sys.stderr)


def _is_glob(pattern: str) -> bool:
    return any(c in pattern for c in "*?[")


def iter_map_files(tree: Path) -> list[tuple[FileMapEntry, Path]]:
    """Expand FILE_MAP against a tree; non-glob misses are fatal."""
    base = files_dir(tree)
    out: list[tuple[FileMapEntry, Path]] = []
    for entry in FILE_MAP:
        matches = [p for p in sorted(base.glob(entry.src)) if p.is_file()]
        if not matches and not _is_glob(entry.src):
            raise FileNotFoundError(base / entry.src)
        out.extend((entry, m) for m in matches)
    return out


def dest_path(ctx: SyncContext, entry: FileMapEntry, src: Path) -> Path:
    d = ctx.dest(entry.dest_dir)
    if entry.preserve_parent:
        return d / src.parent.name / src.name
    return d / src.name


def _render(ctx: SyncContext, entry: FileMapEntry, src: Path) -> bytes:
    return src.read_bytes()


def _sudoers_ok(data: bytes) -> bool:
    with tempfile.NamedTemporaryFile(suffix=".sudoers") as tf:
        tf.write(data)
        tf.flush()
        try:
            r = subprocess.run(["visudo", "-cf", tf.name], capture_output=True)
        except FileNotFoundError:
            # No visudo → refuse the write (safe default; a real Pi
            # always has it via the sudo package).
            return False
    return r.returncode == 0


def install_file(ctx: SyncContext, entry: FileMapEntry, src: Path) -> bool:
    """Install one mapped file. Returns True when it changed (or
    would change under --dry-run)."""
    data = _render(ctx, entry, src)
    dest = dest_path(ctx, entry, src)
    same = (
        dest.exists()
        and dest.read_bytes() == data
        and (dest.stat().st_mode & 0o777) == entry.mode
    )
    if same:
        return False
    if entry.special == "sudoers" and not _sudoers_ok(data):
        ctx.fail(f"visudo -cf rejected new {dest}; keeping old file")
        return False
    if ctx.dry_run:
        ctx.note(f"would install {dest}")
        return True
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    dest.chmod(entry.mode)
    ctx.note(f"installed {dest}")
    return True
