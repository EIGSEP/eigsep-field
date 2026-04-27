# eigsep-field

Umbrella repo for the EIGSEP field deployment stack. Coordinates the release
train, offline build artifacts, RPi image recipe, and cross-repo issue/PR flow
for the hardware libraries that run on the field Raspberry Pi.

This repo does **not** own the wire contracts. The contract authority is
[`eigsep_redis`](https://github.com/EIGSEP/eigsep_redis) (Transport +
writer/reader-per-bus, `keys.py`) and the `SENSOR_SCHEMAS` in
[`eigsep_observing`](https://github.com/EIGSEP/eigsep_observing). This repo
links to those sources rather than restating them.

## What's in here

- `manifest.toml` — blessed version tuple for a field release.
- `pyproject.toml` — installable `eigsep-field` meta-package; its deps are
  pinned to the manifest via a Hatch metadata hook.
- `uv.lock` / `requirements.txt` — uv is source of truth; pip users read the
  exported `requirements.txt`.
- `scripts/` — wheelhouse build, lockfile refresh, offline installer, sync-PR
  helper.
- `image/pi-gen-config/` — pi-gen stage that bakes the offline wheelhouse and
  firmware blobs into the RPi image.
- `firmware/` — manifests for pico `.uf2` and RFSoC `.npz` (blobs live in
  GitHub Releases, not git).
- `docs/interface/` — permalink index into the contract authority sources.
- `.github/` — issue templates, PR template, and workflows for validate /
  wheelhouse build / image build / downstream sync.

## Stack

| name                  | repo                                        | role                                   |
|-----------------------|---------------------------------------------|----------------------------------------|
| `eigsep_redis`        | EIGSEP/eigsep_redis                         | foundational; contract authority       |
| `picohost`            | EIGSEP/pico-firmware (`picohost/` subpkg)   | Pico host; depends on eigsep_redis     |
| `eigsep-vna`          | EIGSEP/cmt_vna                              | VNA control                            |
| `eigsep_observing`    | EIGSEP/eigsep_observing                     | top orchestrator                       |
| `pyvalon`             | EIGSEP/pyvalon                              | Valon synth CLI; standalone            |
| pico `.uf2`           | EIGSEP/pico-firmware (C/CMake)              | flashed via picotool                   |
| rfsoc `.npz`          | produced from EIGSEP/eigsep_dac             | RFSoC bitstream                        |

## Quickstart (dev host)

```bash
uv venv --python 3.11
uv pip install -e '.[dev]'

# Regenerate lockfile + exported requirements after editing manifest.toml
./scripts/refresh-lock.sh

# Build an offline wheelhouse targeting the Pi
./scripts/build-wheelhouse.sh

# Run CLI
eigsep-field info
eigsep-field doctor
```

Pip-only equivalent:

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'
# `requirements.txt` is committed; `uv export` is run in CI to keep it fresh.
```

## Field install (Pi, offline)

```bash
sudo /opt/eigsep/scripts/install-field.sh
eigsep-field verify
```

The Pis depend on the operator laptop for time discipline (the
dhcp-master Pi serves NTP to the LAN, with the laptop as upstream).
See [docs/operator/laptop-ntp.md](docs/operator/laptop-ntp.md) for
laptop-side setup.

## Release / bump workflow

1. Open a `release-coordination` issue.
2. Edit `manifest.toml`; write `docs/releases/<release>.md`.
3. `./scripts/refresh-lock.sh` — regenerates `uv.lock`, `requirements.txt`.
4. Open PR. Validate CI must pass (lint, manifest-verify, lock-drift, smoke,
   contract tests against the pinned set).
5. Merge and tag `v<release>`. The tag triggers wheelhouse + image builds.

## Cross-repo coordination

- eigsep-field issues are for **cross-cutting** or **contract-change** work.
  Single-repo bugs stay in their home repos.
- A coordinated change uses:
  - Branch name `field/<issue>-<slug>` in every sibling repo
  - PR label `coordinated-change`
  - PR body footer `Refs: EIGSEP/eigsep-field#<issue>`
- `scripts/sync-pr.sh` opens the branches and draft PRs in each sibling.

See [docs/interface/README.md](docs/interface/README.md) for the contract index.
