# Producer contract tests

Every producer (Pico apps via `picohost`, VNA via `cmt_vna`, SNAP via
`eigsep_observing.fpga`) is validated against `SENSOR_SCHEMAS` by the
contract-test suite shipped at
[`eigsep_observing/src/eigsep_observing/contract_tests/`](https://github.com/EIGSEP/eigsep_observing/tree/634bd3e06d7a06af89556b051f9b386a9519feb8/src/eigsep_observing/contract_tests).
The suite lives under `src/` so it installs with the wheel and is reachable
via `pytest --pyargs` on wheel-only hosts (e.g. the Pi).

Cross-package Redis-key uniqueness is enforced by
[`test_key_uniqueness.py`](https://github.com/EIGSEP/eigsep_observing/blob/634bd3e06d7a06af89556b051f9b386a9519feb8/src/eigsep_observing/contract_tests/test_key_uniqueness.py)
in the same subpackage — an import-time collision between
`eigsep_observing.keys` and `eigsep_redis.keys` would silently cross
buses, so the check runs alongside the producer tests on every
`eigsep-field verify`.

## Run them

From an installed stack (pinned to the blessed manifest):

```bash
eigsep-field verify
```

Or directly:

```bash
pytest --pyargs eigsep_observing.contract_tests
```

## If the contract test fails

Fix the producer, not the test. `eigsep_observing`'s design philosophy
(`CLAUDE.md` — "Contract-Based and Defensive") is that contract violations
are upstream bugs, not consumer-side resilience problems.
