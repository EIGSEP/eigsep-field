# Redis key registry

Every Redis key, stream, and set touched by the EIGSEP stack is declared
as a module-level string constant in one of two authoritative modules:

- **`eigsep_redis.keys`** — transport-layer keys (metadata hash + streams,
  status stream, config singleton). Imported by producers and the orchestrator.
- **`eigsep_observing.keys`** — observer-side keys (corr streams, VNA stream).

Cross-package uniqueness is enforced at test time by
`eigsep_observing/src/eigsep_observing/contract_tests/test_key_uniqueness.py`
(ships inside the wheel; runs on every `eigsep-field verify`).

## Naming convention

| Suffix          | Redis type |
|-----------------|------------|
| `_HASH`         | hash |
| `_STREAM`       | stream (`XADD`) |
| `_STREAMS_SET`  | set of stream names |
| `_SET`          | set |
| `_KEY`          | singleton key (opaque value) |

## The keys

<!-- BEGIN GENERATED: redis-keys -->
<!-- Do not edit by hand. Regenerate with ./scripts/gen_interface_docs.py -->
#### `eigsep_redis` (transport layer)

| Constant | Value | Kind |
|---|---|---|
| `CONFIG_KEY` | `'config'` | singleton key |
| `DATA_STREAMS_SET` | `'data_streams'` | set |
| `METADATA_HASH` | `'metadata'` | hash |
| `METADATA_STREAMS_SET` | `'metadata_streams'` | set |
| `STATUS_STREAM` | `'stream:status'` | stream |


#### `eigsep_observing` (observer side)

| Constant | Value | Kind |
|---|---|---|
| `ADC_SNAPSHOT_STREAM` | `'stream:adc_snapshot'` | stream |
| `CORR_CONFIG_KEY` | `'corr_config'` | singleton key |
| `CORR_HEADER_KEY` | `'corr_header'` | singleton key |
| `CORR_PAIRS_SET` | `'corr_pairs'` | set |
| `CORR_STREAM` | `'stream:corr'` | stream |
| `VNA_STREAM` | `'stream:vna'` | stream |
<!-- END GENERATED: redis-keys -->

## Adding a new key

1. Add the constant to **one** module only — transport vs observer-side is the
   rule. Do not duplicate across both.
2. Run `./scripts/gen_interface_docs.py` to refresh this table.
3. Commit the `keys.py` change and the regenerated markdown in the same PR.
4. If the new key crosses repo boundaries (e.g. a new producer stream), open
   a `contract-change` issue first.
