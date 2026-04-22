# Producer contract tests

Every producer (Pico apps via `picohost`, VNA via `cmt_vna`, SNAP via
`eigsep_observing.fpga`) is validated against `SENSOR_SCHEMAS` by the
producer-contract suite shipped at
[`eigsep_observing/src/eigsep_observing/contract_tests/`](https://github.com/EIGSEP/eigsep_observing/tree/main/src/eigsep_observing/contract_tests).
The suite lives under `src/` so it installs with the wheel and is reachable
via `pytest --pyargs` on wheel-only hosts (e.g. the Pi).

Cross-package key uniqueness is enforced by
[`eigsep_observing/tests/test_key_uniqueness.py`](https://github.com/EIGSEP/eigsep_observing/blob/v1.0.0/tests/test_key_uniqueness.py).
(Still in `tests/` — not needed by `eigsep-field verify`; runs in
CI against a cloned eigsep_observing checkout.)

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
