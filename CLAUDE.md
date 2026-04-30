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

## When adding a hardware-only (off-PyPI) package

`[hardware.*]` entries describe Python packages that aren't on PyPI and
are only needed on Pi nodes that talk to real hardware. `casperfpga` is
the current example. They are **not** dependencies of the `eigsep-field`
meta package — ground stack code lazy-imports them — so CI/dev installs
never fetch them. On the Pi, `install-field.sh` installs them from
pre-built aarch64 wheels staged in the wheelhouse.

To add one:

1. Add `[hardware.<name>]` to `manifest.toml` with `version`, `tag`, and
   `source` (git URL of the EIGSEP fork).
2. `./scripts/build-wheelhouse.sh` will cross-build an aarch64 wheel via
   docker + qemu (`scripts/build-git-wheels.sh`) and emit
   `wheels/hardware-requirements.txt` with sha256 hashes.
3. `eigsep-field info`/`doctor` pick it up automatically via the
   `manifest["hardware"]` table.
4. Building requires docker + binfmt-registered qemu-user-static on the
   dev machine running the wheelhouse build. (Native builds are used
   when the host is already the target arch.)

## When adding a systemd service to the image

Services are declared in `manifest.toml` `[services.*]` and driven from
there by image build (`scripts/_image_install.py`'s `enable-always` step),
`eigsep-field doctor`, and `eigsep-field services`. The image is
uniform across Pis; per-Pi differentiation is the role set in
`/boot/eigsep-role.conf` applied by `eigsep-first-boot.service`.

1. Add `[services.<name>]` to `manifest.toml` with:
   - `kind` — `"apt"` (provided by a Debian package), `"local"` (owned by
     this repo), or `"sibling"` (owned by a sibling repo, tracked for
     drift).
   - `unit` — the systemd unit filename.
   - `activation` — `"always"` (enabled on every Pi at build time) or
     `"role"` (enabled on first boot when `/boot/eigsep-role.conf` matches).
   - `role` — required when `activation = "role"`. One of `"panda"`,
     `"backend"`, or `"dhcp-master"`.
   - `source` / `tag` / `source_path` — required for `kind = "sibling"`;
     tag must match the corresponding `[packages.*].tag`.
2. For `kind = "local"` or `kind = "sibling"`, drop the unit file (adapted
   for the image's `/opt/eigsep/venv` layout) in
   `image/pi-gen-config/stage-eigsep/files/systemd/`.
3. For role services, update the role's `.target` (`eigsep-panda.target`,
   `eigsep-backend.target`, `eigsep-dhcp.target`) to `Wants=` the new unit.
4. For `kind = "sibling"`, add a permalink row in
   `docs/interface/README.md` under the Systemd services section.
5. Run `python3 scripts/check_services_drift.py` to confirm tag alignment
   and semantic parity with upstream. CI enforces this via the
   `services-drift` job.

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

We deliberately do **not** use `release-please` here (siblings do): calver
isn't commit-driven, the source of truth is `manifest.toml` rather than
`pyproject.toml`, and there's no PyPI publish to automate — the artifacts
are the wheelhouse and image, both already produced from the tag.
