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
### `imu_el`

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
| `el_deg` | `float` | float → mean of non-error survivors |


### `imu_az`

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
| `el_deg` | `float` | float → mean of non-error survivors |
| `az_deg` | `float` | float → mean of non-error survivors |
| `az_from_accel_deg` | `float` | float → mean of non-error survivors |
| `az_from_yaw_deg` | `float` | float → mean of non-error survivors |
| `az_blend_weight` | `float` | float → mean of non-error survivors |


### `tempctrl_lna`, `tempctrl_load`

Shared schema object — every listed sensor uses exactly the same fields.

| Field | Type | Reduction |
|---|---|---|
| `sensor_name` | `str` | str → first if unanimous, else ``UNKNOWN`` |
| `status` | `str` | str → first if unanimous, else ``UNKNOWN`` |
| `app_id` | `int` | int → min of non-error survivors (expected invariant) |
| `watchdog_tripped` | `bool` | bool → any of non-error survivors |
| `watchdog_timeout_ms` | `int` | int → min of non-error survivors (expected invariant) |
| `T_now` | `float` | float → mean of non-error survivors |
| `voltage` | `float` | float → mean of non-error survivors |
| `resistance` | `float` | float → mean of non-error survivors |
| `timestamp` | `float` | float → mean of non-error survivors |
| `T_target` | `float` | float → mean of non-error survivors |
| `drive_level` | `float` | float → mean of non-error survivors |
| `enabled` | `bool` | bool → any of non-error survivors |
| `active` | `bool` | bool → any of non-error survivors |
| `int_disabled` | `bool` | bool → any of non-error survivors |
| `stall_tripped` | `bool` | bool → any of non-error survivors |
| `cooling_enabled` | `bool` | bool → any of non-error survivors |
| `hysteresis` | `float` | float → mean of non-error survivors |
| `clamp` | `float` | float → mean of non-error survivors |
| `Kp` | `float` | float → mean of non-error survivors |
| `Ki` | `float` | float → mean of non-error survivors |
| `integral` | `float` | float → mean of non-error survivors |


### `potmon`

| Field | Type | Reduction |
|---|---|---|
| `sensor_name` | `str` | str → first if unanimous, else ``UNKNOWN`` |
| `status` | `str` | str → first if unanimous, else ``UNKNOWN`` |
| `app_id` | `int` | int → min of non-error survivors (expected invariant) |
| `pot_az_voltage` | `float` | float → mean of non-error survivors |
| `pot_az_angle` | `float` | float → mean of non-error survivors |
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


### `system_current`

| Field | Type | Reduction |
|---|---|---|
| `sensor_name` | `str` | str → first if unanimous, else ``UNKNOWN`` |
| `status` | `str` | str → first if unanimous, else ``UNKNOWN`` |
| `current_voltage` | `float` | float → mean of non-error survivors |
| `current_a` | `float` | float → mean of non-error survivors |
| `current_cal_slope` | `float` | float → mean of non-error survivors |
| `current_cal_intercept` | `float` | float → mean of non-error survivors |


### `motor`

| Field | Type | Reduction |
|---|---|---|
| `sensor_name` | `str` | str → first if unanimous, else ``UNKNOWN`` |
| `status` | `str` | str → first if unanimous, else ``UNKNOWN`` |
| `app_id` | `int` | int → min of non-error survivors (expected invariant) |
| `boot_id` | `int` | int → min of non-error survivors (expected invariant) |
| `az_pos` | `float` | float → mean of non-error survivors |
| `az_target_pos` | `float` | float → mean of non-error survivors |
| `el_pos` | `float` | float → mean of non-error survivors |
| `el_target_pos` | `float` | float → mean of non-error survivors |


### `adc_stats`

| Field | Type | Reduction |
|---|---|---|
| `sensor_name` | `str` | str → first if unanimous, else ``UNKNOWN`` |
| `status` | `str` | str → first if unanimous, else ``UNKNOWN`` |
| `input0_core0_mean` | `float` | float → mean of non-error survivors |
| `input0_core0_power` | `float` | float → mean of non-error survivors |
| `input0_core0_rms` | `float` | float → mean of non-error survivors |
| `input0_core1_mean` | `float` | float → mean of non-error survivors |
| `input0_core1_power` | `float` | float → mean of non-error survivors |
| `input0_core1_rms` | `float` | float → mean of non-error survivors |
| `input1_core0_mean` | `float` | float → mean of non-error survivors |
| `input1_core0_power` | `float` | float → mean of non-error survivors |
| `input1_core0_rms` | `float` | float → mean of non-error survivors |
| `input1_core1_mean` | `float` | float → mean of non-error survivors |
| `input1_core1_power` | `float` | float → mean of non-error survivors |
| `input1_core1_rms` | `float` | float → mean of non-error survivors |
| `input2_core0_mean` | `float` | float → mean of non-error survivors |
| `input2_core0_power` | `float` | float → mean of non-error survivors |
| `input2_core0_rms` | `float` | float → mean of non-error survivors |
| `input2_core1_mean` | `float` | float → mean of non-error survivors |
| `input2_core1_power` | `float` | float → mean of non-error survivors |
| `input2_core1_rms` | `float` | float → mean of non-error survivors |
| `input3_core0_mean` | `float` | float → mean of non-error survivors |
| `input3_core0_power` | `float` | float → mean of non-error survivors |
| `input3_core0_rms` | `float` | float → mean of non-error survivors |
| `input3_core1_mean` | `float` | float → mean of non-error survivors |
| `input3_core1_power` | `float` | float → mean of non-error survivors |
| `input3_core1_rms` | `float` | float → mean of non-error survivors |
| `input4_core0_mean` | `float` | float → mean of non-error survivors |
| `input4_core0_power` | `float` | float → mean of non-error survivors |
| `input4_core0_rms` | `float` | float → mean of non-error survivors |
| `input4_core1_mean` | `float` | float → mean of non-error survivors |
| `input4_core1_power` | `float` | float → mean of non-error survivors |
| `input4_core1_rms` | `float` | float → mean of non-error survivors |
| `input5_core0_mean` | `float` | float → mean of non-error survivors |
| `input5_core0_power` | `float` | float → mean of non-error survivors |
| `input5_core0_rms` | `float` | float → mean of non-error survivors |
| `input5_core1_mean` | `float` | float → mean of non-error survivors |
| `input5_core1_power` | `float` | float → mean of non-error survivors |
| `input5_core1_rms` | `float` | float → mean of non-error survivors |


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
