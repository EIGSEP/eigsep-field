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

import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from eigsep_field._patch import SRC_ROOT, VENV_PATH, WHEELHOUSE
from eigsep_field._services import (
    entry_for_role,
    parse_role_file,
    systemctl,
)  # noqa: F401 (later steps)

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


def render_template(text: str, release: str, dev_banner: str) -> str:
    if dev_banner:
        text = text.replace("{{dev_banner}}", dev_banner)
    else:
        kept = [ln for ln in text.splitlines() if "{{dev_banner}}" not in ln]
        text = "\n".join(kept) + "\n"
    return text.replace("{{release}}", release)


def read_dev_banner(ctx: SyncContext) -> str:
    """DEV-image banner from the on-Pi manifest's [image] block.

    DEV-ness is a property of the flashed image, not of the tree —
    preserved across syncs (mirrors image.yml's stamp step)."""
    p = ctx.dest("/etc/eigsep/manifest.toml")
    if not p.exists():
        return ""
    img = tomllib.loads(p.read_text()).get("image", {})
    if not img.get("dev"):
        return ""
    sha = img.get("sha", "unknown")
    return f"*** DEV BUILD {sha} — not a blessed release ***"


def _render(ctx: SyncContext, entry: FileMapEntry, src: Path) -> bytes:
    data = src.read_bytes()
    if entry.special == "template":
        text = render_template(
            data.decode(),
            ctx.manifest["release"],
            read_dev_banner(ctx),
        )
        data = text.encode()
    return data


def refresh_etc_manifest(ctx: SyncContext) -> None:
    """Tree manifest → /etc/eigsep/manifest.toml, [image] preserved."""
    dest = ctx.dest("/etc/eigsep/manifest.toml")
    text = (ctx.tree / "manifest.toml").read_text()
    image: dict = {}
    if dest.exists():
        image = tomllib.loads(dest.read_text()).get("image", {})
    if image:
        lines = ["", "[image]"]
        for k, v in image.items():
            if isinstance(v, bool):
                lines.append(f"{k} = {str(v).lower()}")
            else:
                lines.append(f'{k} = "{v}"')
        text += "\n".join(lines) + "\n"
    if dest.exists() and dest.read_text() == text:
        return
    if ctx.dry_run:
        ctx.note(f"would refresh {dest}")
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text)
    ctx.note(f"refreshed {dest}")


REDIS_INCLUDES = (
    (
        "# EIGSEP field overrides — see /etc/redis/redis.conf.d/eigsep.conf",
        "include /etc/redis/redis.conf.d/eigsep.conf",
    ),
    (
        "# EIGSEP role-conditional persistence — symlink managed by\n"
        "# eigsep-field _apply-role; snippets in /etc/eigsep/redis/.",
        "include /etc/redis/redis.conf.d/eigsep-role.conf",
    ),
)


def append_redis_includes(ctx: SyncContext) -> None:
    """Idempotent include lines, mirroring _chroot-install.sh."""
    conf = ctx.dest("/etc/redis/redis.conf")
    if not conf.exists():
        ctx.fail(f"{conf} missing (redis-server not installed?)")
        return
    body = conf.read_text()
    for comment, include in REDIS_INCLUDES:
        if include in body:
            continue
        if ctx.dry_run:
            ctx.note(f"would append '{include}' to {conf}")
            continue
        body += f"\n{comment}\n{include}\n"
        ctx.note(f"appended '{include}' to {conf}")
    if not ctx.dry_run:
        conf.write_text(body)


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


def removed_paths_file(tree: Path) -> Path:
    return tree / STAGE_REL / "removed-paths.txt"


def read_removed_paths(tree: Path) -> list[str]:
    p = removed_paths_file(tree)
    if not p.exists():
        return []
    out = []
    for raw in p.read_text().splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out


RELEASES_BASE = "https://github.com/EIGSEP/eigsep-field"


def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, **kw)


def _download(url: str, dest: Path) -> None:
    req = urllib.request.Request(
        url, headers={"User-Agent": "eigsep-field-sync"}
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        with dest.open("wb") as f:
            shutil.copyfileobj(r, f)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def wheelhouse_pin(wheels: Path) -> str | None:
    """The eigsep-field== pin build-wheelhouse.sh appended, or None."""
    req = wheels / "requirements.txt"
    if not req.exists():
        return None
    m = re.search(
        r"^eigsep[-_]field==([0-9A-Za-z.!+-]+)",
        req.read_text(),
        re.MULTILINE,
    )
    return m.group(1) if m else None


def _pip_install_wheelhouse(ctx: SyncContext) -> None:
    pip = str(VENV_PATH / "bin" / "pip")
    reqs = [WHEELHOUSE / "requirements.txt"]
    hw = WHEELHOUSE / "hardware-requirements.txt"
    if hw.exists():
        reqs.append(hw)
    for req in reqs:
        r = _run(
            [
                pip,
                "install",
                "--no-index",
                "--find-links",
                str(WHEELHOUSE),
                "--require-hashes",
                "-r",
                str(req),
            ]
        )
        if r.returncode != 0:
            ctx.fail(f"pip install -r {req} failed")
            return
    # The blessed wheel just overwrote the self-updated tree install.
    # If the tree is not exactly the blessed tag, put the tree back.
    release = ctx.manifest["release"]
    head = _run(
        ["git", "-C", str(ctx.tree), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
    )
    tag = _run(
        ["git", "-C", str(ctx.tree), "rev-list", "-n1", f"v{release}"],
        capture_output=True,
        text=True,
    )
    if (
        head.returncode != 0
        or tag.returncode != 0
        or head.stdout.strip() != tag.stdout.strip()
    ):
        ctx.note("tree is ahead of blessed tag; reinstalling tree")
        r = _run([pip, "install", "--quiet", str(ctx.tree)])
        if r.returncode != 0:
            ctx.fail("pip install <tree> after swap failed")


def step_wheelhouse(ctx: SyncContext) -> None:
    """Swap /opt/eigsep/wheels to the blessed release artifact."""
    release = ctx.manifest["release"]
    pin = wheelhouse_pin(WHEELHOUSE)
    if pin == release:
        ctx.note(f"wheelhouse already at {release}")
        return
    platform = ctx.manifest.get("system", {}).get("platform", "linux_aarch64")
    asset = f"wheels-{platform}.tar.xz"
    url = f"{RELEASES_BASE}/releases/download/v{release}/{asset}"
    if ctx.dry_run:
        ctx.note(f"would download {url} and reinstall the venv")
        return
    with tempfile.TemporaryDirectory(dir=WHEELHOUSE.parent) as tmpdir:
        td = Path(tmpdir)
        tar = td / asset
        shafile = td / (asset + ".sha256")
        try:
            _download(url, tar)
            _download(url + ".sha256", shafile)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                ctx.note(
                    f"no wheelhouse published for v{release} "
                    "(mid-cycle tree?); skipping venv sync"
                )
                return
            ctx.fail(f"download {url}: {e}")
            return
        except urllib.error.URLError as e:
            ctx.fail(f"download {url}: {e}")
            return
        want = shafile.read_text().split()[0]
        if _sha256(tar) != want:
            ctx.fail(f"sha256 mismatch for {asset}; keeping wheelhouse")
            return
        new = td / "wheels"
        new.mkdir()
        with tarfile.open(tar) as tf:
            tf.extractall(new, filter="data")
        prev = WHEELHOUSE.parent / "wheels.prev"
        if prev.exists():
            shutil.rmtree(prev)
        if WHEELHOUSE.exists():
            WHEELHOUSE.rename(prev)
            (WHEELHOUSE.parent / "previous-release").write_text(
                pin or "unknown"
            )
        shutil.move(str(new), str(WHEELHOUSE))
    ctx.note(f"wheelhouse: {pin or 'none'} -> {release}")
    _pip_install_wheelhouse(ctx)


def step_removals(ctx: SyncContext) -> None:
    """Delete tombstoned paths left behind by older images."""
    for path in read_removed_paths(ctx.tree):
        target = ctx.dest(path)
        if not target.exists() and not target.is_symlink():
            continue
        is_unit = path.startswith("/etc/systemd/system/") and path.endswith(
            (".service", ".target")
        )
        if ctx.dry_run:
            ctx.note(f"would remove {target}")
            continue
        if is_unit:
            unit = Path(path).name
            # rc ignored: "not loaded" is fine, the file still goes.
            systemctl("disable", "--now", unit)
            ctx.changed_units.add(unit)
        if target.is_dir() and not target.is_symlink():
            shutil.rmtree(target)
        else:
            target.unlink()
        ctx.note(f"removed {target}")


def sync_role(ctx: SyncContext) -> str | None:
    return parse_role_file(ctx.dest("/etc/eigsep/role")).role


def step_firmware(ctx: SyncContext) -> None:
    """Refresh blessed firmware blobs. Never flashes hardware."""
    role = sync_role(ctx)
    for kind, entry in ctx.manifest.get("firmware", {}).items():
        asset = entry.get("asset")
        if not asset:
            continue
        if not entry_for_role(entry, role):
            ctx.note(f"firmware {kind}: skipped (role {role})")
            continue
        blessed = ctx.dest(f"/opt/eigsep/firmware/{kind}/{asset}")
        want = entry.get("sha256", "")
        if blessed.exists() and (not want or _sha256(blessed) == want):
            ctx.note(f"firmware {kind}: {asset} up to date")
            continue
        url = f"{entry['source']}/releases/download/{entry['tag']}/{asset}"
        if ctx.dry_run:
            ctx.note(f"would download {url}")
            continue
        tmp = blessed.parent / (asset + ".sync-tmp")
        blessed.parent.mkdir(parents=True, exist_ok=True)
        try:
            _download(url, tmp)
        except (urllib.error.HTTPError, urllib.error.URLError) as e:
            ctx.fail(f"firmware {kind}: download {url}: {e}")
            continue
        if want and _sha256(tmp) != want:
            ctx.fail(f"firmware {kind}: sha256 mismatch; keeping old")
            tmp.unlink()
            continue
        tmp.replace(blessed)
        ctx.note(
            f"firmware {kind}: updated {asset} — flash with "
            "flash-picos / `eigsep-field revert pico-firmware`"
            if kind == "pico"
            else f"firmware {kind}: updated {asset}"
        )
        if (blessed.parent / ".field-patch").exists():
            ctx.note(
                f"firmware {kind}: NOTE a field patch is active; "
                "blessed blob updated but not flashed"
            )


def step_external(ctx: SyncContext) -> None:
    """Install missing [external.*] binaries via their scripts."""
    role = sync_role(ctx)
    for name, entry in ctx.manifest.get("external", {}).items():
        if not entry_for_role(entry, role):
            ctx.note(f"external {name}: skipped (role {role})")
            continue
        binary = ctx.dest(str(Path(entry["install_path"]) / entry["binary"]))
        if binary.exists() and os.access(binary, os.X_OK):
            ctx.note(f"external {name}: present")
            continue
        script = ctx.tree / "scripts" / f"install-{name}.sh"
        if not script.exists():
            ctx.fail(f"external {name}: {script} missing")
            continue
        if ctx.dry_run:
            ctx.note(f"would run {script} (URL fetch)")
            continue
        env = dict(os.environ)
        env["EIGSEP_MANIFEST"] = str(ctx.tree / "manifest.toml")
        r = _run(["bash", str(script)], env=env)
        if r.returncode != 0:
            ctx.fail(f"external {name}: install script failed")
        else:
            ctx.note(f"external {name}: installed")


def _git_kwargs(repo: Path) -> dict:
    """Run git as the clone's owner so root never pollutes .git."""
    kw: dict = {"capture_output": True, "text": True}
    if os.geteuid() == 0:
        st = repo.stat()
        kw["user"] = st.st_uid
        kw["group"] = st.st_gid
    return kw


def step_sources(ctx: SyncContext) -> None:
    """Clone new manifest siblings; refresh blessed-commit markers."""
    from eigsep_field import _image_install

    targets = _image_install._clone_targets(ctx.manifest)
    missing = [t for t in targets if not (SRC_ROOT / t.clone_path).exists()]
    if ctx.dry_run:
        for t in missing:
            ctx.note(f"would clone {t.name} ({t.tag})")
    elif missing:
        ns = argparse.Namespace(src_root=str(SRC_ROOT), user="eigsep")
        if _image_install._cmd_clone_sources(ns):
            ctx.fail("clone-sources reported failures")
    for t in targets:
        repo = SRC_ROOT / t.clone_path
        if not (repo / ".git").exists():
            continue
        kw = _git_kwargs(repo)
        if not ctx.dry_run:
            _run(["git", "-C", str(repo), "fetch", "--tags", "-q"], **kw)
        r = _run(["git", "-C", str(repo), "rev-list", "-n1", t.tag], **kw)
        if r.returncode != 0:
            ctx.fail(f"sources {t.name}: cannot resolve {t.tag}")
            continue
        commit = r.stdout.strip()
        marker = repo / ".eigsep-blessed-commit"
        if marker.exists() and marker.read_text().strip() == commit:
            continue
        if ctx.dry_run:
            ctx.note(f"would refresh blessed marker for {t.name}")
            continue
        st = repo.stat()
        marker.write_text(commit + "\n")
        os.chown(marker, st.st_uid, st.st_gid)
        ctx.note(f"sources {t.name}: blessed = {t.tag} ({commit[:9]})")
