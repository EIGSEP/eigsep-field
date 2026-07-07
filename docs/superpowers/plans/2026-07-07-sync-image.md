# eigsep-field sync-image Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `sudo eigsep-field sync-image` brings an already-flashed Pi up to
the state of the checked-out `/opt/eigsep/src/eigsep-field` tree —
systemd units, /etc overlays, apt packages, wheelhouse+venv, firmware
blobs, external binaries, role settings — online, pre-deployment.

**Architecture:** New module `src/eigsep_field/_sync.py` holds a
declarative file map mirroring `00-run.sh`'s staging plus ordered step
functions sharing a `SyncContext` (fake-rootable for tests). Removals
come from a tombstone file. CI drift tests force the map to stay
complete. Spec: `docs/superpowers/specs/2026-07-07-sync-image-design.md`.

**Tech Stack:** Python 3.13 stdlib only (tomllib, urllib, tarfile,
subprocess), pytest with monkeypatch (repo convention), bash for the
image-stage scripts.

## Global Constraints

- Ruff, line length **79** (`ruff check .` and `ruff format --check .`
  must pass — CI enforces).
- Python 3.13; **no new runtime dependencies** (stdlib only).
- Never hand-edit `pyproject.toml` `[project].dependencies`/`version`.
- Test style: pytest, `tmp_path` fake roots, `monkeypatch.setattr` on
  module-level function references (see `tests/test_apply_role.py`).
- All destinations resolve through `SyncContext.dest()` so tests can
  fake the filesystem root.
- Steps must be idempotent: second run with no tree changes = no-op.
- Commit style: conventional prefixes (`feat:`, `docs:`, `chore:`),
  end commit messages with
  `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- Run tests with `pytest -q tests/<file>` from the repo root.

---

### Task 1: Extract the apt package list to a shared data file

The apt list lives inline in `_chroot-install.sh`; sync-image needs the
same list without parsing bash. Move it to `files/apt-packages.txt`,
consumed by both.

**Files:**
- Create: `image/pi-gen-config/stage-eigsep/00-eigsep-install/files/apt-packages.txt`
- Modify: `image/pi-gen-config/stage-eigsep/00-eigsep-install/files/_chroot-install.sh:39-54`
- Modify: `image/pi-gen-config/stage-eigsep/00-eigsep-install/00-run.sh` (stage the file for the chroot)

**Interfaces:**
- Produces: `files/apt-packages.txt` — one Debian package per line,
  full-line `#` comments and blank lines allowed (no inline comments).
  Task 8's `read_apt_packages()` and Task 9's drift test consume it.

- [ ] **Step 1: Create `files/apt-packages.txt`**

Content (list copied verbatim from `_chroot-install.sh:40-54`; the
rationale comments stay in the shell script):

```
# apt packages installed into the image chroot AND re-applied in place
# by `eigsep-field sync-image`. One package per line. Full-line
# comments only — no inline comments (both consumers strip only lines
# starting with '#').
python3
python3-venv
python3-pip
redis-server
isc-dhcp-server
chrony
picotool
xvfb
libegl1
libopengl0
libfontconfig1
libxkbcommon0
libxkbcommon-x11-0
libxcb-cursor0
libxcb-icccm4
libxcb-keysyms1
libxcb-shape0
libxcb-xkb1
git
curl
vim-nox
screen
arp-scan
tcpdump
tshark
nmap
mtr-tiny
traceroute
iputils-arping
dnsutils
build-essential
pkg-config
libusb-1.0-0-dev
cmake
gcc-arm-none-eabi
libstdc++-arm-none-eabi-newlib
```

- [ ] **Step 2: Point `_chroot-install.sh` at it**

Replace the multi-line `apt-get install` (lines 39–54) with:

```bash
grep -vE '^[[:space:]]*(#|$)' /opt/eigsep/apt-packages.txt \
    | xargs apt-get install -y --no-install-recommends
rm -f /opt/eigsep/apt-packages.txt
```

Keep the big rationale comment block above it (lines 16–38) intact —
it explains *why* the packages are in the list.

- [ ] **Step 3: Stage the file in `00-run.sh`**

In `00-run.sh`, immediately after the `install -m 0644
files/etc-eigsep/manifest.toml ...` line (line 22), add:

```bash
# apt list consumed by _chroot-install.sh inside the chroot (removed
# there after use) and by `eigsep-field sync-image` from the git tree.
install -m 0644 files/apt-packages.txt \
    "${ROOTFS_DIR}/opt/eigsep/apt-packages.txt"
```

- [ ] **Step 4: Syntax-check both scripts**

Run:
`bash -n image/pi-gen-config/stage-eigsep/00-eigsep-install/files/_chroot-install.sh && bash -n image/pi-gen-config/stage-eigsep/00-eigsep-install/00-run.sh && echo OK`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add image/pi-gen-config/stage-eigsep/00-eigsep-install/
git commit -m "chore(image): extract apt package list to apt-packages.txt"
```

---

### Task 2: `_sync.py` core — SyncContext, file map, plain file install

**Files:**
- Create: `src/eigsep_field/_sync.py`
- Test: `tests/test_sync_image.py`

**Interfaces:**
- Consumes: `EIGSEP_FIELD_PROJECT`, `SRC_ROOT`, `VENV_PATH`,
  `WHEELHOUSE` from `eigsep_field._patch`; `systemctl` from
  `eigsep_field._services`.
- Produces (used by every later task):
  - `class SyncContext` — fields `tree: Path`, `manifest: dict`,
    `root: Path`, `dry_run: bool`, `failures: int`,
    `changed_units: set[str]`, `restart_units: set[str]`; methods
    `dest(absolute: str) -> Path`, `note(msg: str) -> None`,
    `fail(msg: str) -> None` (increments `failures`).
  - `class FileMapEntry` — frozen dataclass: `src: str` (glob relative
    to the stage `files/` dir), `dest_dir: str` (absolute), `mode: int
    = 0o644`, `preserve_parent: bool = False`, `unit: str | None =
    None`, `special: str | None = None` (`"template"` | `"sudoers"`).
  - `FILE_MAP: tuple[FileMapEntry, ...]`
  - `files_dir(tree: Path) -> Path`
  - `iter_map_files(tree: Path) -> list[tuple[FileMapEntry, Path]]`
  - `dest_path(ctx, entry, src) -> Path`
  - `install_file(ctx, entry, src) -> bool` (True = changed/would
    change)

- [ ] **Step 1: Write failing tests**

Create `tests/test_sync_image.py`:

```python
"""Tests for eigsep_field._sync — fake-root file staging."""

from __future__ import annotations

from pathlib import Path

import pytest

from eigsep_field import _sync


REPO = Path(__file__).resolve().parent.parent


@pytest.fixture
def tree(tmp_path):
    """Minimal eigsep-field tree with a stage files/ dir."""
    t = tmp_path / "tree"
    f = t / "image/pi-gen-config/stage-eigsep/00-eigsep-install/files"
    (f / "systemd").mkdir(parents=True)
    (f / "systemd" / "demo.service").write_text("[Unit]\nA=1\n")
    (f / "systemd" / "chrony-wait.service.d").mkdir()
    (f / "systemd" / "chrony-wait.service.d" / "eigsep.conf").write_text(
        "[Install]\n"
    )
    (f / "udev").mkdir()
    (f / "udev" / "usb-demo.rules").write_text("RULE\n")
    (t / "manifest.toml").write_text('release = "2026.4.0"\n')
    return t


@pytest.fixture
def ctx(tree, tmp_path):
    import tomllib

    manifest = tomllib.loads((tree / "manifest.toml").read_text())
    return _sync.SyncContext(
        tree=tree, manifest=manifest, root=tmp_path / "root", dry_run=False
    )


def test_dest_resolves_under_root(ctx):
    assert ctx.dest("/etc/motd") == ctx.root / "etc/motd"


def test_install_new_file(ctx, tree):
    entry = _sync.FileMapEntry("systemd/*.service", "/etc/systemd/system")
    src = _sync.files_dir(tree) / "systemd" / "demo.service"
    assert _sync.install_file(ctx, entry, src) is True
    dest = ctx.dest("/etc/systemd/system/demo.service")
    assert dest.read_text() == "[Unit]\nA=1\n"
    assert (dest.stat().st_mode & 0o777) == 0o644


def test_install_unchanged_is_noop(ctx, tree):
    entry = _sync.FileMapEntry("systemd/*.service", "/etc/systemd/system")
    src = _sync.files_dir(tree) / "systemd" / "demo.service"
    _sync.install_file(ctx, entry, src)
    assert _sync.install_file(ctx, entry, src) is False


def test_install_preserve_parent_dropin(ctx, tree):
    entry = _sync.FileMapEntry(
        "systemd/*.service.d/*.conf",
        "/etc/systemd/system",
        preserve_parent=True,
    )
    src = (
        _sync.files_dir(tree)
        / "systemd/chrony-wait.service.d/eigsep.conf"
    )
    assert _sync.install_file(ctx, entry, src) is True
    assert ctx.dest(
        "/etc/systemd/system/chrony-wait.service.d/eigsep.conf"
    ).exists()


def test_dry_run_writes_nothing(ctx, tree):
    ctx.dry_run = True
    entry = _sync.FileMapEntry("udev/*.rules", "/etc/udev/rules.d")
    src = _sync.files_dir(tree) / "udev" / "usb-demo.rules"
    assert _sync.install_file(ctx, entry, src) is True
    assert not ctx.dest("/etc/udev/rules.d/usb-demo.rules").exists()


def test_iter_map_files_missing_nonglob_raises(tmp_path):
    t = tmp_path / "empty"
    _sync.files_dir(t).mkdir(parents=True)
    with pytest.raises(FileNotFoundError):
        _sync.iter_map_files(t)


def test_file_map_covers_real_repo():
    pairs = _sync.iter_map_files(REPO)
    srcs = {p.name for _, p in pairs}
    assert "picomanager.service" in srcs
    assert "usb-cmt-vna.rules" in srcs
    assert "motd" in srcs
    assert "CHEATSHEET.md" in srcs
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest -q tests/test_sync_image.py`
Expected: FAIL / error — `eigsep_field._sync` does not exist.

- [ ] **Step 3: Write `src/eigsep_field/_sync.py`**

```python
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
            r = subprocess.run(
                ["visudo", "-cf", tf.name], capture_output=True
            )
        except FileNotFoundError:
            # No visudo → refuse the write (safe default; a real Pi
            # always has it via the sudo package).
            return False
    return r.returncode == 0


def install_file(
    ctx: SyncContext, entry: FileMapEntry, src: Path
) -> bool:
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
```

(`_render` is a placeholder hook — Task 3 teaches it templating; the
sudoers gate is already live and Task 3 tests it.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest -q tests/test_sync_image.py`
Expected: all PASS.

- [ ] **Step 5: Lint and commit**

```bash
uvx ruff check src/eigsep_field/_sync.py tests/test_sync_image.py
uvx ruff format src/eigsep_field/_sync.py tests/test_sync_image.py
git add src/eigsep_field/_sync.py tests/test_sync_image.py
git commit -m "feat(sync): SyncContext, file map, and file install core"
```

---

### Task 3: Templating, /etc/eigsep/manifest refresh, redis includes, sudoers gate

**Files:**
- Modify: `src/eigsep_field/_sync.py`
- Test: `tests/test_sync_image.py`

**Interfaces:**
- Consumes: Task 2's `SyncContext`, `install_file`, `_render` hook.
- Produces:
  - `render_template(text: str, release: str, dev_banner: str) -> str`
  - `read_dev_banner(ctx) -> str` — parses the on-Pi
    `/etc/eigsep/manifest.toml` `[image]` block; `""` when not a DEV
    image.
  - `refresh_etc_manifest(ctx) -> None` — tree manifest →
    `/etc/eigsep/manifest.toml`, `[image]` block preserved.
  - `append_redis_includes(ctx) -> None` — the two idempotent include
    lines on `/etc/redis/redis.conf`.

- [ ] **Step 1: Write failing tests** (append to `tests/test_sync_image.py`)

```python
def test_render_template_release_and_dev_banner():
    text = "# release {{release}}\n{{dev_banner}}\nbody\n"
    out = _sync.render_template(text, "2026.4.0", "*** DEV abc ***")
    assert "release 2026.4.0" in out
    assert "*** DEV abc ***" in out


def test_render_template_strips_banner_line_when_blessed():
    text = "# release {{release}}\n{{dev_banner}}\nbody\n"
    out = _sync.render_template(text, "2026.4.0", "")
    assert "{{dev_banner}}" not in out
    assert out.splitlines() == ["# release 2026.4.0", "body"]


def test_read_dev_banner(ctx):
    etc = ctx.dest("/etc/eigsep")
    etc.mkdir(parents=True)
    (etc / "manifest.toml").write_text(
        'release = "2026.3.0"\n[image]\ndev = true\nsha = "abc1234"\n'
    )
    assert "abc1234" in _sync.read_dev_banner(ctx)


def test_read_dev_banner_blessed_or_missing(ctx):
    assert _sync.read_dev_banner(ctx) == ""


def test_refresh_etc_manifest_preserves_image_block(ctx):
    etc = ctx.dest("/etc/eigsep")
    etc.mkdir(parents=True)
    (etc / "manifest.toml").write_text(
        'release = "2026.3.0"\n[image]\ndev = true\nsha = "abc1234"\n'
    )
    _sync.refresh_etc_manifest(ctx)
    import tomllib

    m = tomllib.loads((etc / "manifest.toml").read_text())
    assert m["release"] == "2026.4.0"
    assert m["image"] == {"dev": True, "sha": "abc1234"}


def test_append_redis_includes_idempotent(ctx):
    redis = ctx.dest("/etc/redis")
    redis.mkdir(parents=True)
    conf = redis / "redis.conf"
    conf.write_text("bind 127.0.0.1\n")
    _sync.append_redis_includes(ctx)
    _sync.append_redis_includes(ctx)
    body = conf.read_text()
    assert body.count("include /etc/redis/redis.conf.d/eigsep.conf") == 1
    assert (
        body.count("include /etc/redis/redis.conf.d/eigsep-role.conf")
        == 1
    )


def test_sudoers_gate_rejects_bad_file(ctx, tree, monkeypatch):
    f = _sync.files_dir(tree) / "sudoers.d"
    f.mkdir()
    (f / "eigsep-field").write_text("syntactically wrong\n")
    monkeypatch.setattr(_sync, "_sudoers_ok", lambda data: False)
    entry = _sync.FileMapEntry(
        "sudoers.d/eigsep-field",
        "/etc/sudoers.d",
        mode=0o440,
        special="sudoers",
    )
    src = f / "eigsep-field"
    assert _sync.install_file(ctx, entry, src) is False
    assert ctx.failures == 1
    assert not ctx.dest("/etc/sudoers.d/eigsep-field").exists()


def test_template_files_render_on_install(ctx, tree):
    f = _sync.files_dir(tree) / "etc-eigsep"
    f.mkdir(parents=True)
    (f / "motd").write_text("release {{release}}\n{{dev_banner}}\n")
    entry = _sync.FileMapEntry(
        "etc-eigsep/motd", "/etc", special="template"
    )
    _sync.install_file(ctx, entry, f / "motd")
    body = ctx.dest("/etc/motd").read_text()
    assert "release 2026.4.0" in body
    assert "{{dev_banner}}" not in body
```

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `pytest -q tests/test_sync_image.py`
Expected: new tests FAIL (`render_template` not defined, `_render`
doesn't template).

- [ ] **Step 3: Implement in `_sync.py`**

Add `import tomllib` at the top. Replace `_render` and add:

```python
def render_template(text: str, release: str, dev_banner: str) -> str:
    if dev_banner:
        text = text.replace("{{dev_banner}}", dev_banner)
    else:
        kept = [
            ln
            for ln in text.splitlines()
            if "{{dev_banner}}" not in ln
        ]
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
        "# EIGSEP field overrides — see "
        "/etc/redis/redis.conf.d/eigsep.conf",
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest -q tests/test_sync_image.py`
Expected: all PASS.

- [ ] **Step 5: Lint and commit**

```bash
uvx ruff check . && uvx ruff format src tests
git add src/eigsep_field/_sync.py tests/test_sync_image.py
git commit -m "feat(sync): templating, manifest refresh, redis includes"
```

---

### Task 4: Tombstones — removed-paths.txt and the removals step

**Files:**
- Create: `image/pi-gen-config/stage-eigsep/00-eigsep-install/removed-paths.txt`
- Modify: `src/eigsep_field/_sync.py`
- Test: `tests/test_sync_image.py`

**Interfaces:**
- Produces:
  - `removed_paths_file(tree: Path) -> Path`
  - `read_removed_paths(tree: Path) -> list[str]` (absolute paths)
  - `step_removals(ctx) -> None` — uses module-level `systemctl`
    (monkeypatchable).

- [ ] **Step 1: Create the tombstone file**

`image/pi-gen-config/stage-eigsep/00-eigsep-install/removed-paths.txt`:

```
# Paths an OLDER image may contain that a CURRENT image must not.
# `eigsep-field sync-image` deletes each existing path; systemd units
# get `systemctl disable --now` first. Absolute paths, one per line,
# full-line # comments. This list only grows — removing an entry
# does not resurrect anything, it only stops the cleanup.
#
# eigsep-panda.service: deleted 2026-05-14 — panda_observe is
# operator-launched, not a systemd service.
/etc/systemd/system/eigsep-panda.service
```

- [ ] **Step 2: Write failing tests** (append to `tests/test_sync_image.py`)

```python
@pytest.fixture
def fake_systemctl(monkeypatch):
    calls: list[tuple[str, ...]] = []

    def _sc(*args):
        calls.append(args)
        return 0, ""

    monkeypatch.setattr(_sync, "systemctl", _sc)
    return calls


def _write_tombstones(tree, lines):
    p = tree / _sync.STAGE_REL / "removed-paths.txt"
    p.write_text("\n".join(lines) + "\n")


def test_removals_deletes_and_disables_unit(ctx, tree, fake_systemctl):
    _write_tombstones(
        tree, ["# gone", "/etc/systemd/system/eigsep-panda.service"]
    )
    stale = ctx.dest("/etc/systemd/system/eigsep-panda.service")
    stale.parent.mkdir(parents=True)
    stale.write_text("[Unit]\n")
    _sync.step_removals(ctx)
    assert not stale.exists()
    assert (
        "disable",
        "--now",
        "eigsep-panda.service",
    ) in fake_systemctl
    assert "eigsep-panda.service" in ctx.changed_units


def test_removals_missing_path_is_silent_noop(ctx, tree, fake_systemctl):
    _write_tombstones(tree, ["/etc/systemd/system/never-existed.service"])
    _sync.step_removals(ctx)
    assert fake_systemctl == []
    assert ctx.failures == 0


def test_removals_dry_run_keeps_file(ctx, tree, fake_systemctl):
    ctx.dry_run = True
    _write_tombstones(tree, ["/etc/old.conf"])
    old = ctx.dest("/etc/old.conf")
    old.parent.mkdir(parents=True)
    old.write_text("x")
    _sync.step_removals(ctx)
    assert old.exists()
    assert fake_systemctl == []
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest -q tests/test_sync_image.py -k removals`
Expected: FAIL — `step_removals` not defined.

- [ ] **Step 4: Implement in `_sync.py`**

Add `import shutil` at the top, then:

```python
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


def step_removals(ctx: SyncContext) -> None:
    """Delete tombstoned paths left behind by older images."""
    for path in read_removed_paths(ctx.tree):
        target = ctx.dest(path)
        if not target.exists() and not target.is_symlink():
            continue
        is_unit = path.startswith(
            "/etc/systemd/system/"
        ) and path.endswith((".service", ".target"))
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
```

- [ ] **Step 5: Run tests, lint, commit**

Run: `pytest -q tests/test_sync_image.py && uvx ruff check .`
Expected: all PASS.

```bash
git add image/pi-gen-config/stage-eigsep/00-eigsep-install/removed-paths.txt \
    src/eigsep_field/_sync.py tests/test_sync_image.py
git commit -m "feat(sync): tombstone removals for stale image paths"
```

---

### Task 5: Wheelhouse + venv step

**Files:**
- Modify: `src/eigsep_field/_sync.py`
- Test: `tests/test_sync_image.py`

**Interfaces:**
- Consumes: `WHEELHOUSE`, `VENV_PATH` from `eigsep_field._patch`.
- Produces:
  - `RELEASES_BASE: str` — module constant
    `"https://github.com/EIGSEP/eigsep-field"`.
  - `wheelhouse_pin(wheels: Path) -> str | None`
  - `_download(url: str, dest: Path) -> None` (monkeypatch target)
  - `_run(cmd: list[str], **kw) -> subprocess.CompletedProcess`
    (monkeypatch target; shared by later steps)
  - `_sha256(path: Path) -> str`
  - `step_wheelhouse(ctx) -> None`

- [ ] **Step 1: Write failing tests** (append to `tests/test_sync_image.py`)

```python
import hashlib
import subprocess
import tarfile


def _make_wheel_tar(tmp_path, release):
    src = tmp_path / "wh-src"
    src.mkdir()
    (src / "requirements.txt").write_text(
        f"somepkg==1.0\neigsep-field=={release} \\\n"
        "    --hash=sha256:deadbeef\n"
    )
    tar = tmp_path / "wheels-linux_aarch64.tar.xz"
    with tarfile.open(tar, "w:xz") as tf:
        for p in src.iterdir():
            tf.add(p, arcname=p.name)
    sha = hashlib.sha256(tar.read_bytes()).hexdigest()
    return tar, sha


def test_wheelhouse_pin_parses_appended_line(tmp_path):
    (tmp_path / "requirements.txt").write_text(
        "a==1\neigsep-field==2026.4.0 \\\n    --hash=sha256:ff\n"
    )
    assert _sync.wheelhouse_pin(tmp_path) == "2026.4.0"


def test_wheelhouse_skips_when_pin_matches(ctx, tmp_path, monkeypatch):
    wh = tmp_path / "wheels"
    wh.mkdir()
    (wh / "requirements.txt").write_text("eigsep-field==2026.4.0\n")
    monkeypatch.setattr(_sync, "WHEELHOUSE", wh)
    called = []
    monkeypatch.setattr(
        _sync, "_download", lambda *a: called.append(a)
    )
    _sync.step_wheelhouse(ctx)
    assert called == []
    assert ctx.failures == 0


def test_wheelhouse_swap_and_pip(ctx, tmp_path, monkeypatch):
    tar, sha = _make_wheel_tar(tmp_path, "2026.4.0")
    wh = tmp_path / "opt" / "wheels"
    wh.mkdir(parents=True)
    (wh / "requirements.txt").write_text("eigsep-field==2026.3.0\n")
    monkeypatch.setattr(_sync, "WHEELHOUSE", wh)

    def fake_download(url, dest):
        if url.endswith(".sha256"):
            dest.write_text(f"{sha}  wheels-linux_aarch64.tar.xz\n")
        else:
            dest.write_bytes(tar.read_bytes())

    monkeypatch.setattr(_sync, "_download", fake_download)
    runs = []

    def fake_run(cmd, **kw):
        runs.append(cmd)
        # git commands fail (fake tree has no tag) → the post-swap
        # tree reinstall must trigger; everything else succeeds.
        rc = 1 if cmd[0] == "git" else 0
        return subprocess.CompletedProcess(cmd, rc, "", "")

    monkeypatch.setattr(_sync, "_run", fake_run)
    _sync.step_wheelhouse(ctx)
    assert _sync.wheelhouse_pin(wh) == "2026.4.0"
    assert (wh.parent / "wheels.prev" / "requirements.txt").exists()
    assert (wh.parent / "previous-release").read_text() == "2026.3.0"
    pip = str(_sync.VENV_PATH / "bin" / "pip")
    assert any(c[:2] == [pip, "install"] and "-r" in c for c in runs)
    assert any(str(ctx.tree) in c for c in runs)  # tree reinstall


def test_wheelhouse_sha_mismatch_keeps_old(ctx, tmp_path, monkeypatch):
    tar, _ = _make_wheel_tar(tmp_path, "2026.4.0")
    wh = tmp_path / "opt" / "wheels"
    wh.mkdir(parents=True)
    (wh / "requirements.txt").write_text("eigsep-field==2026.3.0\n")
    monkeypatch.setattr(_sync, "WHEELHOUSE", wh)

    def fake_download(url, dest):
        if url.endswith(".sha256"):
            dest.write_text("0" * 64 + "  wheels-linux_aarch64.tar.xz\n")
        else:
            dest.write_bytes(tar.read_bytes())

    monkeypatch.setattr(_sync, "_download", fake_download)
    _sync.step_wheelhouse(ctx)
    assert ctx.failures == 1
    assert _sync.wheelhouse_pin(wh) == "2026.3.0"


def test_wheelhouse_404_warns_and_skips(ctx, tmp_path, monkeypatch):
    import urllib.error

    wh = tmp_path / "wheels"
    wh.mkdir()
    (wh / "requirements.txt").write_text("eigsep-field==2026.3.0\n")
    monkeypatch.setattr(_sync, "WHEELHOUSE", wh)

    def fake_download(url, dest):
        raise urllib.error.HTTPError(url, 404, "nf", {}, None)

    monkeypatch.setattr(_sync, "_download", fake_download)
    _sync.step_wheelhouse(ctx)
    assert ctx.failures == 0  # mid-cycle: warn, not fail
    assert _sync.wheelhouse_pin(wh) == "2026.3.0"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest -q tests/test_sync_image.py -k wheelhouse`
Expected: FAIL — names not defined.

- [ ] **Step 3: Implement in `_sync.py`**

Add imports `hashlib`, `re`, `sys`, `tarfile`, `urllib.error`,
`urllib.request`, and `from eigsep_field._patch import VENV_PATH,
WHEELHOUSE`. Then:

```python
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
    platform = ctx.manifest.get("system", {}).get(
        "platform", "linux_aarch64"
    )
    asset = f"wheels-{platform}.tar.xz"
    url = f"{RELEASES_BASE}/releases/download/v{release}/{asset}"
    if ctx.dry_run:
        ctx.note(f"would download {url} and reinstall the venv")
        return
    with tempfile.TemporaryDirectory(
        dir=WHEELHOUSE.parent
    ) as tmpdir:
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
```

- [ ] **Step 4: Run tests, lint, commit**

Run: `pytest -q tests/test_sync_image.py && uvx ruff check .`
Expected: all PASS.

```bash
git add src/eigsep_field/_sync.py tests/test_sync_image.py
git commit -m "feat(sync): wheelhouse swap + venv reinstall step"
```

---

### Task 6: Firmware and external-binary steps

**Files:**
- Modify: `src/eigsep_field/_sync.py`
- Test: `tests/test_sync_image.py`

**Interfaces:**
- Consumes: `entry_for_role`, `parse_role_file` from
  `eigsep_field._services`; `_download`, `_sha256`, `_run` from Task 5.
- Produces:
  - `sync_role(ctx) -> str | None` — role from the fake-rootable
    `/etc/eigsep/role`.
  - `step_firmware(ctx) -> None`
  - `step_external(ctx) -> None`

- [ ] **Step 1: Write failing tests** (append to `tests/test_sync_image.py`)

```python
@pytest.fixture
def panda_ctx(ctx):
    role = ctx.dest("/etc/eigsep/role")
    role.parent.mkdir(parents=True, exist_ok=True)
    role.write_text("role = panda\n")
    ctx.manifest["firmware"] = {
        "pico": {
            "asset": "pico_multi.uf2",
            "source": "https://github.com/EIGSEP/pico-firmware",
            "tag": "v4.1.0",
            "sha256": "",
            "roles": ["panda"],
        },
        "rfsoc": {
            "asset": "rfsoc_2026.tar.gz",
            "source": "https://github.com/EIGSEP/eigsep_dac",
            "tag": "v0.3.0",
            "sha256": "",
            "roles": ["backend"],
        },
    }
    return ctx


def test_firmware_downloads_missing_blob(panda_ctx, monkeypatch):
    got = []

    def fake_download(url, dest):
        got.append(url)
        dest.write_bytes(b"UF2")

    monkeypatch.setattr(_sync, "_download", fake_download)
    _sync.step_firmware(panda_ctx)
    blessed = panda_ctx.dest("/opt/eigsep/firmware/pico/pico_multi.uf2")
    assert blessed.read_bytes() == b"UF2"
    assert got == [
        "https://github.com/EIGSEP/pico-firmware"
        "/releases/download/v4.1.0/pico_multi.uf2"
    ]  # rfsoc is backend-only: not fetched on panda


def test_firmware_present_no_pin_is_kept(panda_ctx, monkeypatch):
    blessed = panda_ctx.dest("/opt/eigsep/firmware/pico/pico_multi.uf2")
    blessed.parent.mkdir(parents=True)
    blessed.write_bytes(b"OLD")
    monkeypatch.setattr(
        _sync,
        "_download",
        lambda *a: pytest.fail("must not download"),
    )
    _sync.step_firmware(panda_ctx)
    assert blessed.read_bytes() == b"OLD"


def test_firmware_sha_mismatch_refetches(panda_ctx, monkeypatch):
    import hashlib as h

    panda_ctx.manifest["firmware"]["pico"]["sha256"] = h.sha256(
        b"NEW"
    ).hexdigest()
    blessed = panda_ctx.dest("/opt/eigsep/firmware/pico/pico_multi.uf2")
    blessed.parent.mkdir(parents=True)
    blessed.write_bytes(b"OLD")
    monkeypatch.setattr(
        _sync, "_download", lambda url, dest: dest.write_bytes(b"NEW")
    )
    _sync.step_firmware(panda_ctx)
    assert blessed.read_bytes() == b"NEW"


def test_external_installs_when_binary_missing(panda_ctx, monkeypatch):
    panda_ctx.manifest["external"] = {
        "cmtvna": {
            "install_path": "/opt/eigsep/cmt-vna",
            "binary": "bin/cmtvna",
            "roles": ["panda"],
        }
    }
    script = panda_ctx.tree / "scripts" / "install-cmtvna.sh"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text("#!/bin/bash\n")
    runs = []
    monkeypatch.setattr(
        _sync,
        "_run",
        lambda cmd, **kw: (
            runs.append(cmd),
            subprocess.CompletedProcess(cmd, 0),
        )[1],
    )
    _sync.step_external(panda_ctx)
    assert runs and runs[0][0] == "bash"
    assert runs[0][1].endswith("install-cmtvna.sh")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest -q tests/test_sync_image.py -k "firmware or external"`
Expected: FAIL — steps not defined.

- [ ] **Step 3: Implement in `_sync.py`**

Add `import os` and extend the `_services` import with
`entry_for_role, parse_role_file`. Then:

```python
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
        if blessed.exists() and (
            not want or _sha256(blessed) == want
        ):
            ctx.note(f"firmware {kind}: {asset} up to date")
            continue
        url = (
            f"{entry['source']}/releases/download/"
            f"{entry['tag']}/{asset}"
        )
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
        binary = ctx.dest(
            str(Path(entry["install_path"]) / entry["binary"])
        )
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
```

- [ ] **Step 4: Run tests, lint, commit**

Run: `pytest -q tests/test_sync_image.py && uvx ruff check .`
Expected: all PASS.

```bash
git add src/eigsep_field/_sync.py tests/test_sync_image.py
git commit -m "feat(sync): firmware blob and external binary steps"
```

---

### Task 7: Sources step — clone new siblings, refresh blessed markers

**Files:**
- Modify: `src/eigsep_field/_sync.py`
- Test: `tests/test_sync_image.py`

**Interfaces:**
- Consumes: `_image_install._cmd_clone_sources`,
  `_image_install._clone_targets`; `SRC_ROOT` from `_patch`.
- Produces: `step_sources(ctx) -> None`.

Note: `SRC_ROOT` is read from `EIGSEP_SRC` at import time; tests
monkeypatch `_sync.SRC_ROOT` directly.

- [ ] **Step 1: Write failing tests** (append to `tests/test_sync_image.py`)

```python
def _git(*args, cwd):
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        env={
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t",
            "PATH": "/usr/bin:/bin",
            "HOME": str(cwd),
        },
    )


def test_sources_refreshes_blessed_marker(ctx, tmp_path, monkeypatch):
    # upstream repo with two tags
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    _git("init", "-q", cwd=upstream)
    (upstream / "f").write_text("1")
    _git("add", "f", cwd=upstream)
    _git("commit", "-qm", "one", cwd=upstream)
    _git("tag", "v1.0.0", cwd=upstream)
    (upstream / "f").write_text("2")
    _git("commit", "-aqm", "two", cwd=upstream)
    _git("tag", "v2.0.0", cwd=upstream)

    src_root = tmp_path / "src"
    src_root.mkdir()
    subprocess.run(
        ["git", "clone", "-q", "-b", "v1.0.0", str(upstream), "demo"],
        cwd=src_root,
        check=True,
        capture_output=True,
    )
    old = "0" * 40
    (src_root / "demo" / ".eigsep-blessed-commit").write_text(
        old + "\n"
    )
    monkeypatch.setattr(_sync, "SRC_ROOT", src_root)
    ctx.manifest["packages"] = {
        "demo": {
            "source": str(upstream),
            "tag": "v2.0.0",
            "version": "2.0.0",
        }
    }
    _sync.step_sources(ctx)
    marker = (
        (src_root / "demo" / ".eigsep-blessed-commit")
        .read_text()
        .strip()
    )
    v2 = subprocess.run(
        ["git", "rev-list", "-n1", "v2.0.0"],
        cwd=upstream,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert marker == v2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest -q tests/test_sync_image.py -k sources`
Expected: FAIL — `step_sources` not defined.

- [ ] **Step 3: Implement in `_sync.py`**

Add `import argparse` and `from eigsep_field._patch import SRC_ROOT`
(extend the existing `_patch` import). Then:

```python
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
    missing = [
        t for t in targets if not (SRC_ROOT / t.clone_path).exists()
    ]
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
            _run(
                ["git", "-C", str(repo), "fetch", "--tags", "-q"], **kw
            )
        r = _run(
            ["git", "-C", str(repo), "rev-list", "-n1", t.tag], **kw
        )
        if r.returncode != 0:
            ctx.fail(f"sources {t.name}: cannot resolve {t.tag}")
            continue
        commit = r.stdout.strip()
        marker = repo / ".eigsep-blessed-commit"
        if (
            marker.exists()
            and marker.read_text().strip() == commit
        ):
            continue
        if ctx.dry_run:
            ctx.note(f"would refresh blessed marker for {t.name}")
            continue
        st = repo.stat()
        marker.write_text(commit + "\n")
        os.chown(marker, st.st_uid, st.st_gid)
        ctx.note(f"sources {t.name}: blessed = {t.tag} ({commit[:9]})")
```

- [ ] **Step 4: Run tests, lint, commit**

Run: `pytest -q tests/test_sync_image.py && uvx ruff check .`
Expected: all PASS.

```bash
git add src/eigsep_field/_sync.py tests/test_sync_image.py
git commit -m "feat(sync): sources step with blessed-marker refresh"
```

---

### Task 8: Orchestration — remaining steps, run_sync, CLI wiring, sudoers

**Files:**
- Modify: `src/eigsep_field/_sync.py`
- Modify: `src/eigsep_field/cli.py` (add parser + `_cmd_sync_image`)
- Modify: `image/pi-gen-config/stage-eigsep/00-eigsep-install/files/sudoers.d/eigsep-field`
- Test: `tests/test_sync_image.py`

**Interfaces:**
- Consumes: everything above; `_cmd_apply_role`, `_cmd_doctor` from
  `cli` (lazy import to avoid the circular import — `cli` imports
  `_sync`); `_cmd_enable_always` from `_image_install`.
- Produces:
  - `step_apt(ctx)`, `step_files(ctx)`, `step_systemd(ctx)`,
    `step_role(ctx)`, `step_dirs(ctx)`, `step_verify(ctx)`
  - `read_apt_packages(tree: Path) -> list[str]`
  - `STEP_ORDER: tuple[str, ...] = ("apt", "wheelhouse", "files",
    "removals", "systemd", "role", "sources", "firmware", "external",
    "dirs", "verify")` and `STEPS: dict[str, callable]`
  - `run_sync(args: argparse.Namespace) -> int` — args fields: `src`,
    `root` (hidden, tests), `dry_run`, `skip: list[str] | None`,
    `only: list[str] | None`.

- [ ] **Step 1: Write failing tests** (append to `tests/test_sync_image.py`)

```python
def test_read_apt_packages_skips_comments(tree):
    f = _sync.files_dir(tree) / "apt-packages.txt"
    f.write_text("# c\n\npython3\nchrony\n")
    assert _sync.read_apt_packages(tree) == ["python3", "chrony"]


def test_step_files_tracks_units_and_restarts(ctx, tree):
    f = _sync.files_dir(tree)
    (f / "dhcp").mkdir()
    (f / "dhcp" / "dhcpd.conf").write_text("subnet {}\n")
    (f / "dhcp" / "isc-dhcp-server").write_text("INTERFACESv4=eth0\n")
    # redis.conf must exist for the include-append
    rc = ctx.dest("/etc/redis/redis.conf")
    rc.parent.mkdir(parents=True)
    rc.write_text("bind 0.0.0.0\n")
    (f / "redis").mkdir()
    for n in ("eigsep.conf", "ephemeral.conf", "persistent.conf"):
        (f / "redis" / n).write_text(f"# {n}\n")
    (f / "chrony").mkdir()
    (f / "chrony" / "client.conf").write_text("server x\n")
    (f / "etc-eigsep").mkdir()
    (f / "etc-eigsep" / "uv.toml").write_text("[pip]\n")
    (f / "etc-eigsep" / "motd").write_text("r {{release}}\n")
    (f / "etc-profile-d").mkdir()
    (f / "etc-profile-d" / "eigsep.sh").write_text("export A=1\n")
    (f / "sudoers.d").mkdir()
    (f / "sudoers.d" / "eigsep-field").write_text("eigsep ALL=x\n")
    (f / "CHEATSHEET.md").write_text("# {{release}}\n")
    import unittest.mock as mock

    with mock.patch.object(_sync, "_sudoers_ok", return_value=True):
        _sync.step_files(ctx)
    assert "demo.service" in ctx.changed_units
    assert "chrony-wait.service" in ctx.changed_units
    assert "isc-dhcp-server.service" in ctx.restart_units
    assert ctx.dest("/etc/eigsep/manifest.toml").exists()


def test_run_sync_dry_run_smoke_on_real_repo(capsys):
    import argparse

    args = argparse.Namespace(
        src=str(REPO),
        root="/",
        dry_run=True,
        skip=None,
        only=["files", "removals"],
    )
    rc = _sync.run_sync(args)
    out = capsys.readouterr().out
    assert "files" in out
    assert rc == 0 or rc == 1  # dev box may lack /etc/redis


def test_run_sync_only_and_skip_selection():
    sel = _sync.select_steps(only=["files", "verify"], skip=["verify"])
    assert sel == ["files"]
    assert _sync.select_steps(only=None, skip=None) == list(
        _sync.STEP_ORDER
    )


def test_cli_wires_sync_image(monkeypatch):
    from eigsep_field import cli

    seen = {}
    monkeypatch.setattr(
        cli, "run_sync", lambda args: seen.setdefault("ok", 0)
    )
    rc = cli.main(["sync-image", "--dry-run"])
    assert rc == 0
    assert seen == {"ok": 0}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest -q tests/test_sync_image.py -k "apt or step_files or run_sync or cli_wires"`
Expected: FAIL — names not defined.

- [ ] **Step 3: Implement the remaining steps in `_sync.py`**

Add `import sys` if not present. Then:

```python
def read_apt_packages(tree: Path) -> list[str]:
    p = files_dir(tree) / "apt-packages.txt"
    out = []
    for raw in p.read_text().splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out


def step_apt(ctx: SyncContext) -> None:
    pkgs = read_apt_packages(ctx.tree)
    if ctx.dry_run:
        ctx.note(f"would apt-get install {len(pkgs)} packages")
        return
    if _run(["apt-get", "update"]).returncode != 0:
        ctx.fail("apt-get update failed")
        return
    r = _run(
        [
            "apt-get",
            "install",
            "-y",
            "--no-install-recommends",
            "-o",
            "Dpkg::Options::=--force-confold",
            *pkgs,
        ]
    )
    if r.returncode != 0:
        ctx.fail("apt-get install failed")
    else:
        ctx.note(f"apt: {len(pkgs)} packages present")


def step_files(ctx: SyncContext) -> None:
    udev_changed = False
    for entry, src in iter_map_files(ctx.tree):
        try:
            changed = install_file(ctx, entry, src)
        except OSError as e:
            ctx.fail(f"{src.name}: {e}")
            continue
        if not changed:
            continue
        if entry.dest_dir == "/etc/systemd/system":
            if entry.preserve_parent:
                ctx.changed_units.add(src.parent.name[: -len(".d")])
            else:
                ctx.changed_units.add(src.name)
        if entry.src.startswith("udev/"):
            udev_changed = True
        if entry.unit:
            ctx.restart_units.add(entry.unit)
    refresh_etc_manifest(ctx)
    append_redis_includes(ctx)
    if udev_changed and not ctx.dry_run:
        if _run(["udevadm", "control", "--reload"]).returncode != 0:
            ctx.fail("udevadm control --reload failed")


def step_systemd(ctx: SyncContext) -> None:
    if ctx.dry_run:
        ctx.note("would daemon-reload + enable always-services")
        return
    if ctx.changed_units:
        rc, msg = systemctl("daemon-reload")
        if rc != 0:
            ctx.fail(f"daemon-reload: {msg}")
        for unit in sorted(ctx.changed_units):
            ctx.note(f"unit changed: {unit} (restart to adopt)")
    from eigsep_field import _image_install

    if _image_install._cmd_enable_always(None):
        ctx.fail("enable-always reported failures")
    # keep timesyncd from fighting chrony (mirrors _chroot-install.sh)
    systemctl("disable", "systemd-timesyncd.service")
    systemctl("mask", "systemd-timesyncd.service")
    for unit in sorted(ctx.restart_units):
        systemctl("try-reload-or-restart", unit)


def step_role(ctx: SyncContext) -> None:
    if ctx.dry_run:
        ctx.note("would re-apply role (hostname, IP, snippets, units)")
        return
    from eigsep_field import cli as _cli

    if _cli._cmd_apply_role(argparse.Namespace(role_conf=None)):
        ctx.fail("_apply-role reported failures")


def step_dirs(ctx: SyncContext) -> None:
    if ctx.dry_run:
        ctx.note("would ensure dirs, ownership, and symlinks")
        return
    for d in ("/opt/eigsep/captures", "/opt/eigsep/cmt-vna/bin"):
        p = ctx.dest(d)
        p.mkdir(parents=True, exist_ok=True)
    for d in (
        "/opt/eigsep/captures",
        "/opt/eigsep/cmt-vna",
        "/opt/eigsep/cmt-vna/bin",
    ):
        try:
            shutil.chown(ctx.dest(d), "eigsep", "eigsep")
        except (KeyError, LookupError):
            ctx.note("user 'eigsep' missing; skipping chown")
            break
    links = [
        ("/usr/local/bin/eigsep-field", VENV_PATH / "bin/eigsep-field"),
        ("/home/eigsep/src", ctx.dest("/opt/eigsep/src")),
        ("/home/eigsep/captures", ctx.dest("/opt/eigsep/captures")),
        (
            "/home/eigsep/CHEATSHEET.md",
            ctx.dest("/opt/eigsep/CHEATSHEET.md"),
        ),
    ]
    for link, target in links:
        lp = ctx.dest(link)
        if link.startswith("/home/") and not lp.parent.is_dir():
            continue
        lp.parent.mkdir(parents=True, exist_ok=True)
        if lp.is_symlink() or lp.exists():
            lp.unlink()
        lp.symlink_to(target)


def step_verify(ctx: SyncContext) -> None:
    if ctx.dry_run:
        ctx.note("would run eigsep-field doctor")
        return
    from eigsep_field import cli as _cli

    rc = _cli._cmd_doctor(argparse.Namespace())
    # Advisory only: doctor can flag things sync can't fix.
    ctx.note(f"doctor: {'OK' if rc == 0 else 'REPORTED PROBLEMS'}")


STEP_ORDER: tuple[str, ...] = (
    "apt",
    "wheelhouse",
    "files",
    "removals",
    "systemd",
    "role",
    "sources",
    "firmware",
    "external",
    "dirs",
    "verify",
)

STEPS = {
    "apt": step_apt,
    "wheelhouse": step_wheelhouse,
    "files": step_files,
    "removals": step_removals,
    "systemd": step_systemd,
    "role": step_role,
    "sources": step_sources,
    "firmware": step_firmware,
    "external": step_external,
    "dirs": step_dirs,
    "verify": step_verify,
}


def select_steps(
    only: list[str] | None, skip: list[str] | None
) -> list[str]:
    sel = [s for s in STEP_ORDER if not only or s in only]
    return [s for s in sel if not skip or s not in skip]


def _self_update(args: argparse.Namespace, tree: Path) -> None:
    """pip-install the tree, then re-exec once on the new code."""
    if os.environ.get("EIGSEP_SYNC_REEXEC"):
        return
    if args.only and "self-update" not in args.only:
        return
    if args.skip and "self-update" in args.skip:
        return
    print("== self-update ==")
    pip = str(VENV_PATH / "bin" / "pip")
    r = _run([pip, "install", "--quiet", str(tree)])
    if r.returncode != 0:
        print("  warn: self-update pip install failed; continuing",
              file=sys.stderr)
        return
    os.environ["EIGSEP_SYNC_REEXEC"] = "1"
    os.execv(
        sys.executable,
        [sys.executable, "-m", "eigsep_field.cli", *sys.argv[1:]],
    )


def run_sync(args: argparse.Namespace) -> int:
    tree = Path(args.src) if args.src else EIGSEP_FIELD_PROJECT
    if not (tree / "manifest.toml").exists():
        print(f"no manifest.toml under {tree}", file=sys.stderr)
        return 2
    if not args.dry_run and os.geteuid() != 0:
        print("sync-image must run as root (sudo)", file=sys.stderr)
        return 2
    # Behind-upstream warning only on real runs: --dry-run stays
    # fully offline/read-only.
    if (tree / ".git").exists() and not args.dry_run:
        kw = _git_kwargs(tree)
        _run(["git", "-C", str(tree), "fetch", "-q"], **kw)
        r = _run(
            [
                "git",
                "-C",
                str(tree),
                "rev-list",
                "--count",
                "HEAD..@{upstream}",
            ],
            **kw,
        )
        behind = r.stdout.strip() if r.returncode == 0 else "0"
        if behind not in ("", "0"):
            print(
                f"warn: tree is {behind} commit(s) behind upstream — "
                "git pull first if that's unintended",
                file=sys.stderr,
            )
    if not args.dry_run:
        _self_update(args, tree)
    manifest = tomllib.loads((tree / "manifest.toml").read_text())
    ctx = SyncContext(
        tree=tree,
        manifest=manifest,
        root=Path(getattr(args, "root", "/") or "/"),
        dry_run=args.dry_run,
    )
    for name in select_steps(args.only, args.skip):
        print(f"== {name} ==")
        STEPS[name](ctx)
    print(
        f"sync-image: {ctx.failures} failure(s)"
        + (" [dry-run]" if ctx.dry_run else "")
    )
    return 1 if ctx.failures else 0
```

Also add `from eigsep_field._patch import EIGSEP_FIELD_PROJECT` to the
existing `_patch` import line.

- [ ] **Step 4: Wire the CLI in `cli.py`**

Add to the imports block:

```python
from eigsep_field._sync import STEP_ORDER, run_sync
```

Add a thin command handler near `_cmd_doctor`:

```python
def _cmd_sync_image(args: argparse.Namespace) -> int:
    return run_sync(args)
```

In `main()`, after the `services` parser block, add:

```python
    sync = sub.add_parser(
        "sync-image",
        help="ONLINE pre-deployment: bring this flashed Pi up to the "
        "checked-out eigsep-field tree (needs sudo)",
    )
    sync.set_defaults(func=_cmd_sync_image)
    sync.add_argument("--dry-run", action="store_true")
    step_names = ["self-update", *STEP_ORDER]
    sync.add_argument(
        "--skip", action="append", choices=step_names, default=None
    )
    sync.add_argument(
        "--only", action="append", choices=step_names, default=None
    )
    sync.add_argument(
        "--src", default=None, help="eigsep-field tree to sync from"
    )
    sync.add_argument("--root", default="/", help=argparse.SUPPRESS)
```

- [ ] **Step 5: Add sync-image to the sudoers drop-in**

In `image/pi-gen-config/stage-eigsep/00-eigsep-install/files/sudoers.d/eigsep-field`,
after the `revert` line add:

```
# `eigsep-field sync-image` is the ONLINE pre-deployment updater; it
# rewrites /etc and the venv, so it needs root like patch/revert.
eigsep ALL=(root) NOPASSWD: /usr/local/bin/eigsep-field sync-image
```

- [ ] **Step 6: Run the full suite, lint, commit**

Run: `pytest -q tests/test_sync_image.py && uvx ruff check . && uvx ruff format --check src tests`
Expected: all PASS.

```bash
git add src/eigsep_field/_sync.py src/eigsep_field/cli.py \
    tests/test_sync_image.py \
    image/pi-gen-config/stage-eigsep/00-eigsep-install/files/sudoers.d/eigsep-field
git commit -m "feat(sync): orchestration, CLI wiring, self-update"
```

---

### Task 9: Drift guards — test_sync_map.py + CI wiring

**Files:**
- Create: `tests/test_sync_map.py`
- Modify: `.github/workflows/validate.yml`

**Interfaces:**
- Consumes: `FILE_MAP`, `iter_map_files`, `dest_path`,
  `read_removed_paths`, `read_apt_packages`, `SyncContext` from
  `_sync`.

- [ ] **Step 1: Write the drift tests**

Create `tests/test_sync_map.py`:

```python
"""Drift guards: the sync-image file map must mirror the image stage.

The image build (00-run.sh) and `eigsep-field sync-image` (_sync.py)
both stage the files/ tree. These tests fail CI when a file is added
to the stage without teaching the sync map about it, and when
tombstones contradict the live map.
"""

from __future__ import annotations

from pathlib import Path

from eigsep_field import _sync

REPO = Path(__file__).resolve().parent.parent
FILES = _sync.files_dir(REPO)

# Build-time-only inputs the sync map intentionally does not stage.
EXCLUDED = {
    "_chroot-install.sh",  # runs only inside the pi-gen chroot
    "apt-packages.txt",  # consumed by the apt step, not file-copied
}


def test_every_staged_file_is_mapped_or_excluded():
    mapped = {p for _, p in _sync.iter_map_files(REPO)}
    unmapped = []
    for p in FILES.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(FILES)
        if rel.parts[0] in EXCLUDED or rel.name in EXCLUDED:
            continue
        if p not in mapped:
            unmapped.append(str(rel))
    assert not unmapped, (
        "files staged by the image but unknown to sync-image "
        f"(add to _sync.FILE_MAP or EXCLUDED): {unmapped}"
    )


def test_map_sources_all_exist():
    # iter_map_files raises FileNotFoundError on a missing non-glob
    pairs = _sync.iter_map_files(REPO)
    assert pairs


def test_tombstones_do_not_collide_with_map():
    import tomllib

    manifest = tomllib.loads((REPO / "manifest.toml").read_text())
    ctx = _sync.SyncContext(tree=REPO, manifest=manifest)
    dests = {
        str(_sync.dest_path(ctx, e, s))
        for e, s in _sync.iter_map_files(REPO)
    }
    for tomb in _sync.read_removed_paths(REPO):
        assert tomb not in dests, (
            f"{tomb} is tombstoned AND still installed by the map"
        )


def test_apt_packages_file_parses_nonempty():
    pkgs = _sync.read_apt_packages(REPO)
    assert "python3" in pkgs
    assert all(" " not in p for p in pkgs)


def test_removed_paths_are_absolute():
    for tomb in _sync.read_removed_paths(REPO):
        assert tomb.startswith("/"), tomb
```

- [ ] **Step 2: Run the tests**

Run: `pytest -q tests/test_sync_map.py`
Expected: all PASS (the map from Task 2 covers the real tree; Task 4
created the tombstone file).

- [ ] **Step 3: Wire into CI**

In `.github/workflows/validate.yml`, find the step named
`Service unit CLI flag tripwire` (the job that installs the blessed
stack and already installs pytest). Immediately after that step, add:

```yaml
      - name: sync-image drift + unit tests
        run: pytest -q tests/test_sync_map.py tests/test_sync_image.py
```

- [ ] **Step 4: Commit**

```bash
git add tests/test_sync_map.py .github/workflows/validate.yml
git commit -m "test(sync): drift guards for the sync-image file map"
```

---

### Task 10: Operator + contributor docs

**Files:**
- Create: `docs/operator/update-pi.md`
- Modify: `CLAUDE.md`
- Modify: `docs/operator/new-pi.md` (one see-also line)

- [ ] **Step 1: Write `docs/operator/update-pi.md`**

```markdown
# Updating a flashed Pi in place (pre-deployment)

`eigsep-field sync-image` brings an already-flashed Pi up to the state
of the checked-out `/opt/eigsep/src/eigsep-field` tree without pulling
the SD card. It is an ONLINE tool: run it before deployment, while the
Pi still has internet (GitHub, PyPI, apt mirrors). In the field, the
only mutation tools remain `eigsep-field patch/revert/capture`.

## One-time bootstrap

Deployed images may predate the command. Once per Pi:

    cd /opt/eigsep/src/eigsep-field && git pull
    sudo /opt/eigsep/venv/bin/pip install .
    sudo eigsep-field sync-image

## Routine use

    cd /opt/eigsep/src/eigsep-field && git pull
    sudo eigsep-field sync-image

The command self-updates from the tree and re-executes, then runs
these steps (see `--skip` / `--only` to cherry-pick):

| step      | what it does                                            |
|-----------|---------------------------------------------------------|
| apt       | installs the image's apt list (files/apt-packages.txt)  |
| wheelhouse| swaps /opt/eigsep/wheels to the blessed release artifact|
| files     | systemd units, /etc overlays, motd/CHEATSHEET, sudoers  |
| removals  | deletes tombstoned paths (removed-paths.txt)            |
| systemd   | daemon-reload + enable always-services                  |
| role      | re-applies hostname, static IP, chrony/redis, role units|
| sources   | clones new siblings, refreshes blessed-commit markers   |
| firmware  | refreshes blessed blobs (never flashes hardware)        |
| external  | installs missing vendor binaries (cmtvna)               |
| dirs      | ownership + symlinks                                    |
| verify    | runs `eigsep-field doctor`                              |

Preview everything first with:

    eigsep-field sync-image --dry-run

Notes:

- The wheelhouse step needs a published release for the tree's
  manifest `release`; on a mid-cycle tree it warns and skips — use
  `git pull` + `eigsep-field patch` in the sibling trees as usual.
- If the blessed Pico UF2 changed, flash it explicitly with
  `flash-picos` (or `eigsep-field revert pico-firmware`).
- The role step restarts redis-server; don't run mid-observation.
- Re-running is always safe: every step is idempotent.
```

- [ ] **Step 2: Add the see-also to `docs/operator/new-pi.md`**

Near the top (after the intro paragraph), add:

```markdown
> Updating an already-flashed Pi instead? See
> [update-pi.md](update-pi.md) — `eigsep-field sync-image` does it in
> place, no SD-card pull needed.
```

- [ ] **Step 3: Add the contributor rule to `CLAUDE.md`**

New section after "When adding a systemd service to the image":

```markdown
## When adding/removing files staged by the image

`eigsep-field sync-image` replays the image stage on a live Pi from a
declarative map in `src/eigsep_field/_sync.py` (`FILE_MAP`).
`tests/test_sync_map.py` fails CI when a file under
`image/pi-gen-config/stage-eigsep/00-eigsep-install/files/` is not
covered by the map (or exempted in its `EXCLUDED` set).

- Adding a staged file: if an existing glob (e.g. `systemd/*.service`)
  covers it, nothing to do; otherwise add a `FileMapEntry`.
- Removing/renaming a staged file that older images shipped: add the
  old absolute path to
  `image/pi-gen-config/stage-eigsep/00-eigsep-install/removed-paths.txt`
  so sync-image cleans it up in place.
- apt list lives in `files/apt-packages.txt` (consumed by both
  `_chroot-install.sh` and sync-image) — not in the shell script.
```

- [ ] **Step 4: Commit**

```bash
git add docs/operator/update-pi.md docs/operator/new-pi.md CLAUDE.md
git commit -m "docs: operator + contributor docs for sync-image"
```

---

## Final verification (after all tasks)

- [ ] `pytest -q tests/` — full suite green (pre-existing tests
  unaffected).
- [ ] `uvx ruff check . && uvx ruff format --check .` — clean.
- [ ] `eigsep-field sync-image --dry-run --src .` on the dev box —
  prints the plan, exits without mutating anything.
- [ ] `bash -n` both image-stage shell scripts.
