# Sensor schemas

`SENSOR_SCHEMAS` in [`eigsep_observing/io.py`](https://github.com/EIGSEP/eigsep_observing/blob/main/src/eigsep_observing/io.py)
is the authoritative contract between the hardware producers (Pico apps via
`picohost`, VNA via `cmt_vna`, SNAP via `eigsep_observing.fpga`) and the
corr/VNA consumers. Each schema is a mapping of `field_name -> python_type`,
validated on ingest by `io._validate_metadata`.

## Reduction policy is derived from the type

When the corr loop averages a sensor's readings across one integration, the
reduction depends on the field's declared type:

| Type    | Reduction policy                               | Rationale |
|---------|------------------------------------------------|-----------|
| `float` | mean of non-error survivors                    | matches the integration's physical meaning |
| `int`   | min of non-error survivors                     | every int field is an invariant constant (`app_id`, `watchdog_timeout_ms`); `min` is a no-op on agreement, and disagreement is caught by a throttled ERROR log |
| `bool`  | any of non-error survivors                     | bool fields are fault flags; `any` preserves a fault that occurred mid-integration |
| `str`   | first value if unanimous, else `"UNKNOWN"`     | matches the rfswitch convention |

Errored samples are filtered before reduction. A per-row `status` of `"error"`
collapses when any raw sample in the integration errored, giving downstream a
single "this row is suspect" signal.

Two helpers bypass the generic reducer:
- `_avg_rfswitch_metadata` returns the bare switch-state name string
- `_avg_temp_metadata` splits the top-level keys from the per-channel
  `LNA_*` / `LOAD_*` keys into sub-dicts

**If you change a field's type, you change its reduction.** That's a
contract change — open a `contract-change` issue before doing it.

## Picohost scalar-only contract

Every field emitted through `picohost.base.redis_handler` must be scalar. Lists
are flattened into per-component scalars. The `potmon` schema in particular is
enforced against the **post-`_pot_redis_handler`** shape (emulator emits raw
voltages; the handler adds calibration slope/intercept + derived angle).

## Schemas

The tables below are regenerated from live imports of `eigsep_observing.io` by
`./scripts/gen_interface_docs.py`. Test suite fails if they drift.

<!-- BEGIN GENERATED: sensor-schemas -->
<!-- Do not edit by hand. Regenerate with ./scripts/gen_interface_docs.py -->
### `imu_el`, `imu_az`

Shared schema object — every listed sensor uses exactly the same fields.

| Field | Type | Reduction |
|---|---|---|
| `sensor_name` | `str` | str → first if unanimous, else ``UNKNOWN`` |
| `status` | `str` | str → first if unanimous, else ``UNKNOWN`` |
| `app_id` | `int` | int → min of non-error survivors (expected invariant) |
| `yaw` | `float` | float → mean of non-error survivors |
| `pitch` | `float` | float → mean of non-error survivors |
| `roll` | `float` | float → mean of non-error survivors |
| `accel_x` | `float` | float → mean of non-error survivors |
| `accel_y` | `float` | float → mean of non-error survivors |
| `accel_z` | `float` | float → mean of non-error survivors |


### `tempctrl`

| Field | Type | Reduction |
|---|---|---|
| `sensor_name` | `str` | str → first if unanimous, else ``UNKNOWN`` |
| `app_id` | `int` | int → min of non-error survivors (expected invariant) |
| `watchdog_tripped` | `bool` | bool → any of non-error survivors |
| `watchdog_timeout_ms` | `int` | int → min of non-error survivors (expected invariant) |
| `LNA_status` | `str` | str → first if unanimous, else ``UNKNOWN`` |
| `LNA_T_now` | `float` | float → mean of non-error survivors |
| `LNA_timestamp` | `float` | float → mean of non-error survivors |
| `LNA_T_target` | `float` | float → mean of non-error survivors |
| `LNA_drive_level` | `float` | float → mean of non-error survivors |
| `LNA_enabled` | `bool` | bool → any of non-error survivors |
| `LNA_active` | `bool` | bool → any of non-error survivors |
| `LNA_int_disabled` | `bool` | bool → any of non-error survivors |
| `LNA_hysteresis` | `float` | float → mean of non-error survivors |
| `LNA_clamp` | `float` | float → mean of non-error survivors |
| `LOAD_status` | `str` | str → first if unanimous, else ``UNKNOWN`` |
| `LOAD_T_now` | `float` | float → mean of non-error survivors |
| `LOAD_timestamp` | `float` | float → mean of non-error survivors |
| `LOAD_T_target` | `float` | float → mean of non-error survivors |
| `LOAD_drive_level` | `float` | float → mean of non-error survivors |
| `LOAD_enabled` | `bool` | bool → any of non-error survivors |
| `LOAD_active` | `bool` | bool → any of non-error survivors |
| `LOAD_int_disabled` | `bool` | bool → any of non-error survivors |
| `LOAD_hysteresis` | `float` | float → mean of non-error survivors |
| `LOAD_clamp` | `float` | float → mean of non-error survivors |


### `potmon`

| Field | Type | Reduction |
|---|---|---|
| `sensor_name` | `str` | str → first if unanimous, else ``UNKNOWN`` |
| `status` | `str` | str → first if unanimous, else ``UNKNOWN`` |
| `app_id` | `int` | int → min of non-error survivors (expected invariant) |
| `pot_el_voltage` | `float` | float → mean of non-error survivors |
| `pot_az_voltage` | `float` | float → mean of non-error survivors |
| `pot_el_angle` | `float` | float → mean of non-error survivors |
| `pot_az_angle` | `float` | float → mean of non-error survivors |
| `pot_el_cal_slope` | `float` | float → mean of non-error survivors |
| `pot_el_cal_intercept` | `float` | float → mean of non-error survivors |
| `pot_az_cal_slope` | `float` | float → mean of non-error survivors |
| `pot_az_cal_intercept` | `float` | float → mean of non-error survivors |


### `rfswitch`

| Field | Type | Reduction |
|---|---|---|
| `sensor_name` | `str` | str → first if unanimous, else ``UNKNOWN`` |
| `status` | `str` | str → first if unanimous, else ``UNKNOWN`` |
| `app_id` | `int` | int → min of non-error survivors (expected invariant) |
| `sw_state` | `int` | int → min of non-error survivors (expected invariant) |
| `sw_state_name` | `str` | str → first if unanimous, else ``UNKNOWN`` |


### `lidar`

| Field | Type | Reduction |
|---|---|---|
| `sensor_name` | `str` | str → first if unanimous, else ``UNKNOWN`` |
| `status` | `str` | str → first if unanimous, else ``UNKNOWN`` |
| `app_id` | `int` | int → min of non-error survivors (expected invariant) |
| `distance_m` | `float` | float → mean of non-error survivors |


### VNA S11 header (`VNA_S11_HEADER_SCHEMA`)

Published alongside each VNA measurement. `freqs` (numpy array) is validated separately from these scalar fields.

| Field | Type | Reduction |
|---|---|---|
| `fstart` | `float` | float → mean of non-error survivors |
| `fstop` | `float` | float → mean of non-error survivors |
| `npoints` | `int` | int → min of non-error survivors (expected invariant) |
| `ifbw` | `float` | float → mean of non-error survivors |
| `power_dBm` | `float` | float → mean of non-error survivors |
| `mode` | `str` | str → first if unanimous, else ``UNKNOWN`` |
| `metadata_snapshot_unix` | `float` | float → mean of non-error survivors |


### VNA S11 structural keys

| Constant | Members |
|---|---|
| `VNA_S11_CAL_KEYS` | `cal:VNAL`, `cal:VNAO`, `cal:VNAS` |
| `VNA_S11_MODE_DATA_KEYS['ant']` | `ant`, `load`, `noise` |
| `VNA_S11_MODE_DATA_KEYS['rec']` | `rec` |
<!-- END GENERATED: sensor-schemas -->

## Also see

- [bus-roles.md](bus-roles.md) — which role owns which writer / reader
- [producer-contracts.md](producer-contracts.md) — the test suite that
  validates every producer against these schemas
