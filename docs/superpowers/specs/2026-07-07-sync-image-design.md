# eigsep-field sync-image — design

Date: 2026-07-07
Status: approved

## Problem

Once a Pi is flashed, the Python stack can be updated in place (`git pull`
+ `eigsep-field patch`, or a new wheelhouse + `install-field.sh`), but
everything the image build stages outside the venv cannot: systemd unit
files, /etc overlays (dhcp, redis, chrony, udev, sudoers, profile.d,
uv.toml), apt packages, firmware blobs, motd/CHEATSHEET, and role
settings. Pulling the SD card to reflash is mechanically hard on the
installed hardware.

`sync-image` is a pre-deployment, online tool: it runs while the Pi
still has internet and brings a flashed image up to the state of the
checked-out `/opt/eigsep/src/eigsep-field` tree, so the image is fully
prepared before the campaign goes offline. It is explicitly allowed to
assume network access (GitHub, PyPI, apt mirrors, vendor CDNs).

## Non-goals

- Not an offline/field tool. In the field, `patch`/`revert`/`capture`
  remain the only mutation paths.
- Does not flash firmware onto attached hardware. It refreshes blessed
  blobs on disk only and tells the operator which flash command to run.
- Does not touch the operator's sibling working trees (no checkout, no
  pull) beyond `git fetch` and refreshing `.eigsep-blessed-commit`.
- Does not replace the image build. `00-run.sh` / `_chroot-install.sh`
  stay authoritative for building images.

## Approach (decided)

A declarative Python sync module (`src/eigsep_field/_sync.py`) that
mirrors what the image stage installs, plus a tombstone list for
removals, plus CI drift tests that force the mirror to stay complete.
Alternatives rejected: re-running the stage scripts with `ROOTFS_DIR=/`
(scripts assume build context; would rsync nonexistent `files/wheels/`
over the live wheelhouse) and extracting a shared file-spec consumed by
both build and sync (rewrites the proven image pipeline to serve a
convenience tool).

## Command surface

```
sudo eigsep-field sync-image [--dry-run] [--skip STEP]... [--only STEP]... [--src PATH]
```

- New module `src/eigsep_field/_sync.py`; cli.py wiring like
  `patch`/`revert`. Requires root (early check, as `_apply-role` does).
- Source tree: `/opt/eigsep/src/eigsep-field` by default, `EIGSEP_SRC`
  env respected (consistent with `_patch.py`), `--src` for tests.
- The manifest is loaded **from the tree** (`<tree>/manifest.toml`),
  not from the installed wheel: the tree is the sync target.
- `--dry-run`: print every planned action (file diffs as
  new/changed/removed, would-install apt packages, would-enable units,
  would-download URLs); no mutations, no self-update re-exec.
- `--skip`/`--only` take step names: `self-update`, `apt`,
  `wheelhouse`, `files`, `removals`, `systemd`, `role`, `sources`,
  `firmware`, `external`, `dirs`, `verify`. Preflight always runs.

## Step pipeline

1. **preflight** — tree exists and is a git repo. `git fetch` as the
   owning user; warn (informational only) if the tree is behind origin.
2. **self-update** — `pip install <tree>` into `/opt/eigsep/venv`, then
   re-exec `sync-image` once (env-var guard, e.g.
   `EIGSEP_SYNC_REEXEC=1`) so the remaining steps run on current sync
   logic. Skipped under `--dry-run`.
3. **apt** — the package list moves from `_chroot-install.sh` into
   `image/pi-gen-config/stage-eigsep/00-eigsep-install/files/apt-packages.txt`
   (one package per line, `#` comments). `_chroot-install.sh` switches
   to reading it (`xargs -ra`); sync-image consumes the same file.
   Runs `apt-get update` then `apt-get install -y
   --no-install-recommends -o Dpkg::Options::=--force-confold <list>`
   (`--force-confold` keeps our conffiles; the files step overwrites
   them with tree versions anyway).
4. **wheelhouse + venv** — if the tree manifest `release` differs from
   the wheelhouse's own `eigsep-field==<ver>` pin in
   `/opt/eigsep/wheels/requirements.txt` (not "the installed release":
   step 2 just made that equal the tree's, and a previous mid-cycle
   sync may have refreshed `/etc/eigsep/manifest.toml` without any
   wheelhouse existing): download `wheels-linux_aarch64.tar.xz` and
   `.sha256` from the GitHub Release `v<release>` over plain HTTPS,
   verify sha256, unpack in a temp dir, atomically swap into
   `/opt/eigsep/wheels` (previous kept as `wheels.prev`; write
   `/opt/eigsep/previous-release`, which `install-field.sh --revert`
   already references), then re-run the `install-field.sh` pip flow
   (`--no-index --require-hashes` against `requirements.txt` +
   `hardware-requirements.txt`). That pip run reinstalls the blessed
   `eigsep-field` wheel over step 2's tree install; if the tree HEAD is
   not the blessed tag's commit, finish by re-running
   `pip install <tree>` so the synced Pi keeps the tree's own code. If
   the release has no published wheelhouse (mid-cycle tree): warn and
   skip — sibling updates stay on the git-pull + `patch` flow.
5. **files** — declarative map applying everything `00-run.sh` stages:
   - `files/systemd/*.service`, `*.target` → `/etc/systemd/system/`
     (0644); drop-in dirs `*.service.d/`, `*.target.d/` → same layout.
   - `files/chrony/*.conf` → `/etc/eigsep/chrony/`.
   - `files/dhcp/dhcpd.conf` → `/etc/dhcp/dhcpd.conf`;
     `files/dhcp/isc-dhcp-server` → `/etc/default/isc-dhcp-server`.
   - `files/redis/eigsep.conf` → `/etc/redis/redis.conf.d/eigsep.conf`;
     `ephemeral.conf`, `persistent.conf` → `/etc/eigsep/redis/`; plus
     the two idempotent include-line appends to `/etc/redis/redis.conf`
     (mirroring `_chroot-install.sh`).
   - `files/udev/*.rules` → `/etc/udev/rules.d/` +
     `udevadm control --reload`.
   - `files/etc-eigsep/uv.toml` → `/etc/eigsep/uv.toml`;
     `files/etc-profile-d/eigsep.sh` → `/etc/profile.d/eigsep.sh`.
   - `files/sudoers.d/eigsep-field` → `/etc/sudoers.d/eigsep-field`
     (0440), gated on `visudo -cf` of the new content; parse failure
     keeps the old file.
   - `files/CHEATSHEET.md` → `/opt/eigsep/CHEATSHEET.md` and
     `files/etc-eigsep/motd` → `/etc/motd`, templated: `{{release}}`
     from the tree manifest; `{{dev_banner}}` rendered/stripped from
     the on-Pi `/etc/eigsep/manifest.toml` `[image]` block (dev status
     is a property of the flashed image, preserved across syncs).
   - `/etc/eigsep/manifest.toml` refreshed from the tree with the
     existing `[image]` block re-appended.
   - Files are compared before writing; only diffs act. Changed configs
     trigger `systemctl try-reload-or-restart` of their owning unit.
6. **removals** — process the tombstone file (below).
7. **systemd wiring** — `systemctl daemon-reload` if any unit changed
   or was removed; replay `enable-always` (reuse
   `eigsep_field._image_install`); keep `systemd-timesyncd` disabled
   and masked. The build-time `disable isc-dhcp-server` is *not*
   replicated — it existed for pre-role image uniformity; a synced Pi
   has its role.
8. **role replay** — invoke the existing `_apply-role` logic against
   `/boot/firmware/eigsep-role.conf`: hostname, static IP, chrony and
   redis symlinks (redis restart acceptable pre-deployment), and
   `enable --now` of role services, picking up newly added ones.
9. **sources** — replay `clone-sources` (new manifest entries cloned;
   existing clones skipped). For existing clones: `git fetch --tags` as
   the owning user, resolve the tree-manifest tag, refresh
   `.eigsep-blessed-commit` so the doctor drift check compares against
   the current blessed commit. Never moves HEAD.
10. **firmware** — per role-gated `[firmware.*]` entry: if the blessed
    blob is missing or its sha256 mismatches the manifest, download the
    GitHub release asset over HTTPS
    (`https://github.com/<owner>/<repo>/releases/download/<tag>/<asset>`,
    no `gh` needed), verify, install to
    `/opt/eigsep/firmware/<kind>/<asset>`. Never flashes. Prints the
    follow-up flash command and flags an active `.field-patch` marker.
    (amended post-review) When `sha256` is empty (a stable asset name
    that never changes bytes-for-bytes across a tag bump — the current
    pico UF2 case), staleness is judged by a sidecar `<asset>.tag`
    marker instead: written after every successful download, compared
    against the manifest's `[firmware.*].tag`. A missing marker counts
    as stale so the first sync after this change re-downloads once and
    is stable thereafter.
11. **external** — per role-gated `[external.*]` entry (cmtvna):
    binary missing → run `scripts/install-<name>.sh` in URL-fetch mode;
    present → report OK (vendor CDN is not reliably versioned; no
    forced reinstall).
12. **dirs + symlinks** — idempotent: `/opt/eigsep/captures`,
    `/opt/eigsep/cmt-vna{,/bin}` with `eigsep:eigsep` ownership;
    `/usr/local/bin/eigsep-field` symlink; homedir symlinks (`~/src`,
    `~/captures`, `~/CHEATSHEET.md`).
13. **verify** — run `doctor`; print its verdict as the closing
    summary. Process exit code reflects sync-step failures only;
    doctor's result is labeled separately (it can flag conditions sync
    legitimately cannot fix).

## Removals: tombstone file

`image/pi-gen-config/stage-eigsep/00-eigsep-install/removed-paths.txt`
— one absolute path per line, `#` comments. Semantics: "paths an older
image may contain that a current image must not." For each path that
exists: unit files under `/etc/systemd/system` get
`systemctl disable --now` (ignoring not-loaded errors) before deletion;
directories are removed recursively; missing paths are silent no-ops.
The list only grows. Generic paths, not just units — renamed firmware
assets or relocated configs can be tombstoned too.

First entry: `/etc/systemd/system/eigsep-panda.service` (deleted in the
2026-05-14 panda pivot).

## Drift guards (CI)

New `tests/test_sync_map.py` in the existing `validate.yml` pytest job:

- **Completeness**: every file under `files/` (recursive) must be
  either mapped by `_sync.py`'s table or in an explicit build-time-only
  exclude set (`_chroot-install.sh`, `wheels/`, `firmware/`,
  `eigsep-field-src`, `apt-packages.txt` — consumed by the apt step).
  Adding a file to the image stage without teaching sync-image fails CI.
- **Consistency**: no tombstone path collides with a current map
  destination; every map source exists in the tree.

CLAUDE.md's "adding a systemd service" checklist gains a line pointing
at the map.

## Error handling

- Steps are independent: a failure sets exit code ≠ 0 and is reported,
  but later steps still run where safe (failed apt does not block file
  sync; failed wheelhouse download skips only the venv step). All steps
  are idempotent — the recovery is always "resolve, re-run".
- Wheelhouse swap is atomic: download, verify, unpack entirely in a
  temp dir; swap only on success; previous wheelhouse retained.
- Sudoers is gated on `visudo -cf`; a parse failure leaves the old
  file in place.
- Network failures produce per-step messages naming the failing URL.

## Testing

- Unit tests against a fake root (`tmp_path`), same pattern as existing
  `_apply-role` tests: map application (new/changed/unchanged/mode
  bits), tombstone removal with a recorded `systemctl` mock,
  motd/CHEATSHEET templating including dev-banner preservation,
  `[image]`-block preservation in `/etc/eigsep/manifest.toml`,
  wheelhouse swap success and sha-mismatch rejection.
- The drift tests double as regression tests.
- A `--dry-run` smoke test against the real repo tree (mutates
  nothing).

## Docs & bootstrap

- New "Updating a flashed Pi pre-deployment" section in the operator
  docs, with the one-time bootstrap (deployed images predate the
  command):

  ```bash
  cd /opt/eigsep/src/eigsep-field && git pull
  sudo /opt/eigsep/venv/bin/pip install .
  sudo eigsep-field sync-image
  ```

  Subsequent runs are `git pull` + `sudo eigsep-field sync-image`
  (self-update covers the rest).
- The sudoers drop-in gains `sync-image` alongside `patch|revert`.

## Decisions log

- Online-only, pre-deployment tool; internet assumed (user decision).
- Venv sync via the blessed release wheelhouse artifact; mid-cycle
  trees warn-and-skip (user decision).
- Firmware: blessed blobs on disk only, never auto-flash (user
  decision).
- Approach A (declarative Python map + tombstones + CI drift tests)
  over stage-script reuse or a shared file-spec (user decision).
