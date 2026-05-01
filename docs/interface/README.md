# Interface control documents

`eigsep-field` does **not** own the wire contracts between EIGSEP hardware
libraries. The contract authority is the sibling repos themselves. This
directory is a **permalink index** into those authoritative sources.

When you need to know the shape of a Redis key, the schema of a sensor
reading, or the signature of a writer/reader method, follow a link below to
the exact file + line in the producing repo. Permalinks should be pinned to
a git SHA (not `main`) so they stay stable as the repos evolve.

| Surface                        | Authority                                                                                         |
|--------------------------------|---------------------------------------------------------------------------------------------------|
| [Redis key registry](redis-keys.md)          | `eigsep_redis/src/eigsep_redis/keys.py` + `eigsep_observing/src/eigsep_observing/keys.py`         |
| [Sensor schemas](sensor-schemas.md)          | `SENSOR_SCHEMAS` in `eigsep_observing/src/eigsep_observing/io.py`                                 |
| [Bus roles](bus-roles.md)                    | Writer/reader-per-bus pattern; see `eigsep_redis/CLAUDE.md`                                       |
| [Producer contracts](producer-contracts.md)  | `eigsep_observing/src/eigsep_observing/contract_tests/` (producer conformance + key uniqueness)   |
| [Systemd services](#systemd-services)        | Sibling unit files pinned in `manifest.toml` `[services.*]`; drift-checked by `scripts/check_services_drift.py` |

## Systemd services

The Pi image declares systemd services in `manifest.toml` `[services.*]`.
Each sibling-owned unit file is copied into
`image/pi-gen-config/stage-eigsep/files/systemd/` (with paths rewritten
for the image's `/opt/eigsep/venv` layout) and tracked against the
permalink below.

| Service                  | Authority                                                                                                                       |
|--------------------------|---------------------------------------------------------------------------------------------------------------------------------|
| `picomanager`            | [pico-firmware / picohost/pico-manager.service](https://github.com/EIGSEP/pico-firmware/blob/v3.0.0/picohost/pico-manager.service) |
| `cmtvna`                 | [CMT-VNA / scripts/cmtvna.service](https://github.com/EIGSEP/CMT-VNA/blob/v1.3.0/scripts/cmtvna.service)                         |
| `eigsep_observe`         | [eigsep_observing / deploy/systemd/eigsep-observe.service](https://github.com/EIGSEP/eigsep_observing/blob/v2.0.0/deploy/systemd/eigsep-observe.service) |
| `eigsep_observe_writer`  | [eigsep_observing / deploy/systemd/eigsep-observe-writer.service](https://github.com/EIGSEP/eigsep_observing/blob/v2.0.0/deploy/systemd/eigsep-observe-writer.service) |

`redis-server` and `isc-dhcp-server` are apt-provided (no unit file
shipped here). `eigsep-panda.service` and the role targets
(`eigsep-panda.target`, `eigsep-backend.target`, `eigsep-dhcp.target`)
plus `eigsep-first-boot.service` are eigsep-field-owned — no sibling
authority, no drift tracking.

## Structure of each doc

- **Human prose at the top** — design rationale, naming conventions, how to
  add a new entry, links to the authoritative source files.
- **Generated tables** in the middle, fenced by
  `<!-- BEGIN GENERATED: <id> -->` / `<!-- END GENERATED: <id> -->`. Do not
  hand-edit content between markers.
- **Hand-written tail** (if any) — cross-references to sibling docs.

## Regenerating

```bash
./scripts/gen_interface_docs.py            # rewrites generated sections
./scripts/gen_interface_docs.py --check    # exits 1 on drift (used in CI)
```

The generator imports `eigsep_redis.keys`, `eigsep_observing.keys`, and
`eigsep_observing.io` at runtime — those siblings must be installed. CI
installs them at the manifest-pinned versions.

## Drift enforcement

Two gates, both backed by the same logic:

- **`pytest tests/test_interface_docs.py`** — runs on every local `pytest`
  invocation. Skipped (not failed) if the siblings aren't importable, so a
  fresh clone without the stack still passes.
- **`docs-drift` CI job** (in `.github/workflows/validate.yml`) — installs
  the blessed siblings, regenerates, and hard-fails on any diff. This is the
  strict gate; devs can't merge a sibling contract change without bumping
  the manifest and regenerating these docs in the same PR.

## Philosophy

1. **Tables are code-authored.** Schemas rot when hand-written; here, they
   are regenerated from the authoritative Python. The markdown exists so
   a human reader never has to open a `.py` file to understand a contract.
2. **Prose is human-authored.** Everything *outside* the generated markers is
   hand-written and immune to the drift check — design rationale, "how to
   add one," warnings about gotchas. This is where the human knowledge lives.
3. **One place to look.** If a dev wants to know what fields `tempctrl`
   emits, they read `sensor-schemas.md` here. They do not have to clone
   five repos.
