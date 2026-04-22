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

## Versioning

Release identifier is calver (`YYYY.MM[.patch]`). Individual sibling packages
keep their own semver; this repo pins them by `==` in the manifest.
