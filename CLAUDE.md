# CLAUDE.md

Guidance for Claude Code working in `eigsep-field`.

## What this repo is

A thin umbrella over the EIGSEP field stack. It owns:

- `manifest.toml` — blessed version tuple
- an installable `eigsep-field` meta-package pinned to the manifest
- offline wheelhouse build (`scripts/build-wheelhouse.sh`)
- RPi image recipe (`image/pi-gen-config/stage-eigsep/`)
- cross-repo coordination (issue templates + `scripts/sync-pr.sh`)

It does **not** own wire contracts. The contract authority is the sibling
repos — see `docs/interface/README.md` for the permalink index. When an ICD
doc in this repo describes a shape, it must permalink (pinned git SHA) to the
authoritative source.

## Topology / what runs where

Standing facts about which Pi runs what and what each Pi is wired to.
Past sessions have gotten confused on each of these — restating them
here so they're visible before you go grep manifest comments.

- **panda Pi** (Pi 4 today; role is decoupled from hardware). Runs
  `picomanager.service` and `cmtvna.service`. It connects to the
  Pico(s) over USB and is the host that flashes them — that's why
  `[firmware.pico]` is gated `roles = ["panda"]`. The CMT VNA is also
  attached to this Pi.

- **backend Pi** (Pi 5 today). Runs `eigsep-observe.service`,
  `eigsep-observe-writer.service`, `redis-server`, and the LAN's
  `isc-dhcp-server`.
  - It connects to the **SNAP** board and reads correlator data from
    it. `casperfpga` is the SNAP driver and is **required** on
    backend — `[hardware.casperfpga]` has `roles = ["backend"]`. The
    "ground stack lazy-imports it" wording elsewhere in this file is
    about keeping CI/dev slim; on a real backend Pi, missing
    `casperfpga` is an image-build bug, not doctor noise.
  - It is the LAN's DHCP server and NTP server by definition: the
    backend role pins eth0 to `10.10.10.10/24` (via
    `ROLE_STATIC_IPS` in `src/eigsep_field/cli.py`) and enables
    `isc-dhcp-server.service` / serves chrony's `server.conf`.
    `eigsep-role.conf` is just `role = backend` — there is no
    separate `dhcp =` flag.

- **RFSoC** is a separate standalone system. It is **not** a Pi and
  does **not** run the eigsep image. The backend Pi holds the
  bitstream `.npz` at `/opt/eigsep/firmware/rfsoc/` and pushes it to
  the RFSoC over the network. `firmware/rfsoc/loader.py` is vendored
  from `eigsep_dac` as reference payload; `eigsep_dac` itself is not
  part of the pip-installable stack and intentionally so — its code
  lands on the Pi mostly as reference, not as a runtime dep.

## Where to look in siblings

- **Key registry** — `eigsep_redis/src/eigsep_redis/keys.py` plus
  `eigsep_observing/src/eigsep_observing/keys.py`. Cross-package uniqueness
  is tested by
  `eigsep_observing/src/eigsep_observing/contract_tests/test_key_uniqueness.py`
  (shipped inside the wheel alongside the producer-contract suite).
- **Bus surfaces** — `eigsep_redis/src/eigsep_redis/{metadata,status,heartbeat,config}.py`.
  Writer/reader-per-bus is structural: wrong-bus writes are impossible.
- **Sensor schemas** — `SENSOR_SCHEMAS` in
  `eigsep_observing/src/eigsep_observing/io.py`. Schemas are load-bearing
  for averaging reduction (`_avg_sensor_values`).
- **Producer contracts** — `eigsep_observing/src/eigsep_observing/contract_tests/`
  (shipped inside the wheel so `eigsep-field verify` can run them via
  `pytest --pyargs eigsep_observing.contract_tests` on wheel-only installs).
  Don't duplicate them here.
- **Architecture prose** — `eigsep_observing/CLAUDE.md` and
  `eigsep_redis/CLAUDE.md` are authoritative.

## Lint / style

Ruff, line length 79. Matches sibling repos.

## When modifying the manifest

Never hand-edit `pyproject.toml` `[project].dependencies` or `[project].version`.
Both are `dynamic`, injected at build time by `scripts/hatch_manifest_hook.py`
from `manifest.toml`. Change `manifest.toml`, then run
`./scripts/refresh-lock.sh`.

## When adding a new package to the stack

1. Add `[packages.<name>]` to `manifest.toml`.
2. `./scripts/refresh-lock.sh`.
3. Add `<name>` to the smoke-import list in `.github/workflows/validate.yml`
   and in `src/eigsep_field/cli.py` (`info` command).
4. If it ships a contract surface, add a permalink entry in
   `docs/interface/README.md`.

## When adding a field-debug package

`[debug.*]` entries are PyPI packages we want available on field Pis for
interactive debugging (ipython, matplotlib, …) but explicitly NOT pulled
in by `pip install eigsep-field` in CI/dev. They live behind the `debug`
extra: the wheelhouse build (`scripts/build-wheelhouse.sh`) compiles
with `--extra debug` so the offline image has them, while smoke tests
and dev installs stay slim.

To add one:

1. Add `[debug.<name>]` to `manifest.toml` with `pypi` and `version`.
2. The hatch hook (`scripts/hatch_manifest_hook.py`) auto-injects the
   pin into the eigsep-field meta-package's `[debug]` extra at build
   time — no pyproject.toml edit.
3. `./scripts/refresh-lock.sh` to regenerate uv.lock and requirements.txt
   (committed `requirements.txt` does NOT include `[debug]` — only the
   wheelhouse copy does).
4. `eigsep-field info`/`doctor` pick the entry up automatically.

If the same package is already a transitive runtime dep (e.g. matplotlib
via eigsep-vna), pinning it under `[debug.*]` is still useful as a
belt-and-suspenders guarantee the field image keeps it even if the
upstream sibling drops the dep. The version must stay reconcilable with
the transitive resolve.

## When adding a hardware-only (off-PyPI) package

`[hardware.*]` entries describe Python packages that aren't on PyPI and
are only needed on Pi nodes that talk to real hardware. `casperfpga` is
the current example. They are **not** dependencies of the `eigsep-field`
meta package — ground stack code lazy-imports them — so CI/dev installs
never fetch them. On the Pi, `install-field.sh` installs them from
pre-built aarch64 wheels staged in the wheelhouse.

To add one:

1. Add `[hardware.<name>]` to `manifest.toml` with `version`, `tag`,
   `source` (git URL of the EIGSEP fork), and `roles = [...]` listing
   which Pi roles import the package at runtime (e.g. `["backend"]` for
   casperfpga). `eigsep-field doctor` only requires the package to be
   installed on Pis whose role appears in `roles`; on other Pis it's
   reported as skipped. Omit `roles` to require it everywhere.
2. `./scripts/build-wheelhouse.sh` will cross-build an aarch64 wheel via
   docker + qemu (`scripts/build-git-wheels.sh`) and emit
   `wheels/hardware-requirements.txt` with sha256 hashes.
3. `eigsep-field info`/`doctor` pick it up automatically via the
   `manifest["hardware"]` table.
4. Building requires docker + binfmt-registered qemu-user-static on the
   dev machine running the wheelhouse build. (Native builds are used
   when the host is already the target arch.)

`[firmware.*]` entries take the same `roles = [...]` field with the
same semantics — the doctor's firmware blob check is gated identically
(e.g. the rfsoc bitstream is only required on backend).

## When adding a systemd service to the image

Services are declared in `manifest.toml` `[services.*]` and driven from
there by image build (`scripts/_image_install.py`'s `enable-always` step),
`eigsep-field doctor`, and `eigsep-field services`. The image is
uniform across Pis; per-Pi differentiation is the role set in
`/boot/firmware/eigsep-role.conf` applied by `eigsep-first-boot.service`.

1. Add `[services.<name>]` to `manifest.toml` with:
   - `kind` — `"apt"` (provided by a Debian package), `"local"` (owned by
     this repo), or `"sibling"` (owned by a sibling repo, tracked for
     drift).
   - `unit` — the systemd unit filename.
   - `activation` — `"always"` (enabled on every Pi at build time) or
     `"role"` (enabled on first boot when `/boot/firmware/eigsep-role.conf`
     matches).
   - `role` — required when `activation = "role"`. One of `"panda"` or
     `"backend"`.
   - `source` / `tag` / `source_path` — required for `kind = "sibling"`;
     tag must match the corresponding `[packages.*].tag`.
2. For `kind = "local"` or `kind = "sibling"`, drop the unit file (adapted
   for the image's `/opt/eigsep/venv` layout) in
   `image/pi-gen-config/stage-eigsep/00-eigsep-install/files/systemd/`.
3. For role services, update the role's `.target` (`eigsep-panda.target`
   or `eigsep-backend.target`) to `Wants=` the new unit.
4. For `kind = "sibling"`, add a permalink row in
   `docs/interface/README.md` under the Systemd services section.
5. Run `python3 scripts/check_services_drift.py` to confirm tag alignment
   and semantic parity with upstream. CI enforces this via the
   `services-drift` job.

## When adding an external (non-redistributable) binary

`[external.*]` entries describe userspace binaries we cannot redistribute
under eigsep-field's MIT license (proprietary vendor builds — `cmtvna`
is the current example). The image build pre-creates the install
directory with `eigsep:eigsep` ownership; the operator stages the
unpacked tree once after first boot via the per-binary install script.
Distinct from `[firmware.*]`, which is for blobs we *do* ship in
release artifacts.

To add one:

1. Add `[external.<name>]` to `manifest.toml` with:
   - `version` — pinned upstream version (informational; doctor reports it).
   - `url` — vendor's CDN URL for the archive. Stays vendor-controlled;
     a break surfaces as a script-level failure, not a build-time one.
   - `sha256` — optional, populated after first hand-validation. Empty
     means re-running the install accepts whatever the vendor currently
     serves.
   - `install_path` — directory the unpacked tree lands in (canonical:
     `/opt/eigsep/<name>`). Pre-created by `_chroot-install.sh` with
     operator ownership.
   - `binary` — path to the executable relative to `install_path`.
     `doctor` checks that this exists and is executable.
   - `roles = [...]` — Pi roles that import the binary at runtime.
     Same semantics as `[firmware.*].roles` / `[hardware.*].roles`.
2. Add `scripts/install-<name>.sh` mirroring `install-cmtvna.sh`:
   reads `[external.<name>]` from the manifest, accepts either a
   positional local path or fetches the URL, unpacks, stages under
   `install_path`, chowns/chmods. Supports `--check` so doctor can
   probe presence cheaply.
3. Pre-create the install dir in
   `image/pi-gen-config/stage-eigsep/00-eigsep-install/files/_chroot-install.sh`
   alongside the other operator-owned dirs.
4. `eigsep-field info` / `doctor` pick the entry up automatically via
   the `manifest["external"]` table.
5. Add an "Installing the <name> binary" section to
   `docs/operator/new-pi.md` (or the role-specific runbook) so the
   step is part of the bring-up checklist.

The local-file install mode is the expected operator path: the field
image ships WiFi disabled and the panda Pi's only LAN reach is the
eigsep `10.10.10.0/24`, so the operator downloads on a laptop and
`scp`s the archive over.

## When a sibling edits a contract surface (keys, SENSOR_SCHEMAS)

Interface docs (`docs/interface/redis-keys.md`, `sensor-schemas.md`) carry
**generated tables** between `<!-- BEGIN GENERATED: <id> -->` / `<!-- END
GENERATED: <id> -->` markers. Do not hand-edit content inside markers.

After a sibling PR changes a key registry or a `SENSOR_SCHEMAS` entry, the
next eigsep-field release PR must:

1. `pip install` the new sibling version into the dev env (or use editable
   siblings).
2. `./scripts/gen_interface_docs.py` to regenerate.
3. Commit the updated docs alongside the `manifest.toml` bump.

CI enforces this via the `docs-drift` job in `validate.yml` — it installs
the blessed sibling versions, regenerates, and fails if the committed docs
differ. `tests/test_interface_docs.py` is the same check as a pytest.

## Coordination rules

- Single-repo bugs → home repo, not here. `.github/ISSUE_TEMPLATE/config.yml`
  routes accordingly.
- Contract changes → `contract-change` issue here, then `sync-pr.sh` opens
  downstream PRs on `field/<issue>-<slug>` branches.
- Releases → `release-coordination` issue here, follow the checklist in
  its template.
- The public website (`EIGSEP.github.io`) has a Software tab whose
  outbound links are pinned to a single tag in
  `docs/_data/eigsep_field.yml`. Bump it to the new release tag as part
  of the release checklist; the bump retargets every link at once.

## Versioning

Release identifier is calver (`YYYY.MM[.patch]`). One release per field
deployment / observing campaign — this is the blessed version tuple for that
campaign, not a continuously-cut artifact. Individual sibling packages keep
their own semver; this repo pins them by `==` in the manifest.

Calver (not semver) because there is no API surface here to communicate
stability about — the repo is a blessed tuple, so semver bumps would be
performative. The calver value tells the reader when the campaign was cut.

## Cutting a release

Releases are operator-driven and manual. The canonical procedure lives in
`.github/ISSUE_TEMPLATE/release-coordination.yml` — open that issue and
follow its checklist. The tag (`vYYYY.MM.P`) is what triggers
`wheelhouse.yml` and `image.yml`, so push it only after the release PR
(manifest bump + lock refresh + interface-doc regen + release notes) has
merged to `main`.

`image.yml` distinguishes blessed from DEV builds by comparing the
trigger ref against `f"v{manifest['release']}"`. Only an exact match
uploads to the GitHub Release; everything else (workflow_dispatch,
rc-style tags, hotfix-test tags) is DEV-stamped, the rootfs's
`/etc/eigsep/manifest.toml` gets an `[image] dev = true` block, and
motd / `eigsep-field info` render a "*** DEV BUILD <sha> ***" banner.
DEV images are still produced and uploaded as a workflow artifact for
QA; they just can't be confused with a release.

The eigsep-field source tree shipped on the image at
`/opt/eigsep/src/eigsep-field` is staged from the runner's
`actions/checkout` (the SHA that triggered the build), not re-cloned
from upstream by `_image_install.clone-sources`. This makes the on-image
tree structurally pinned to the trigger SHA — no chance of skew between
the manifest's release field and the actual tag.

We deliberately do **not** use `release-please` here (siblings do): calver
isn't commit-driven, the source of truth is `manifest.toml` rather than
`pyproject.toml`, and there's no PyPI publish to automate — the artifacts
are the wheelhouse and image, both already produced from the tag.
