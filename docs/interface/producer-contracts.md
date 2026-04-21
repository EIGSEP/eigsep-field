# Producer contract tests

Every producer (Pico apps via `picohost`, VNA via `cmt_vna`, SNAP via
`eigsep_observing.fpga`) is validated against `SENSOR_SCHEMAS` by
[`eigsep_observing/tests/test_producer_contracts.py`](https://github.com/EIGSEP/eigsep_observing/blob/v1.0.0/tests/test_producer_contracts.py).

Cross-package key uniqueness is enforced by
[`eigsep_observing/tests/test_key_uniqueness.py`](https://github.com/EIGSEP/eigsep_observing/blob/v1.0.0/tests/test_key_uniqueness.py).

## Run them

From an installed stack (pinned to the blessed manifest):

```bash
eigsep-field verify
```

Or directly:

```bash
pytest --pyargs eigsep_observing.tests.test_producer_contracts
pytest --pyargs eigsep_observing.tests.test_key_uniqueness
```

The `--pyargs` form works once `eigsep_observing` ships its `tests/` dir as
installed package data (tracked upstream). Until then, `eigsep-field verify`
falls back to cloning the repo at the manifest tag and invoking `pytest`
against it.

## If the contract test fails

Fix the producer, not the test. `eigsep_observing`'s design philosophy
(`CLAUDE.md` — "Contract-Based and Defensive") is that contract violations
are upstream bugs, not consumer-side resilience problems.
