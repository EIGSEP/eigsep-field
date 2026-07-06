# On-demand `cmtvna.service` — design

- **Date:** 2026-07-06
- **Author:** Christian Hellum Bye (with Claude)
- **Status:** Draft — pending review
- **Repos touched:** `eigsep_observing` (bulk), `eigsep-field` (this repo),
  `cmt_vna` (optional)

## Problem

`cmtvna.service` runs the proprietary CMT R60 binary as a socket server
(port 5025, via `xvfb-run`) on the **panda** Pi, enabled at boot and
running 24/7. The binary busy-loops at ~300% CPU **whether or not anyone
is connected**, heating the Pi. We only use it to measure S11 — roughly
once per hour, occasionally in bursts. We want the service off when it
isn't measuring, but transparently available whenever `measure_s11` is
called in code.

## Constraints discovered (these shape the design)

1. **Only stopping the process saves CPU.** The binary pegs the CPU even
   idle; there is no idle-throttle to exploit. So the design must
   `systemctl stop` it, not merely keep it idle.
2. **The VNA socket is persistent and stateful.** `cmt_vna.VNA.__init__`
   opens a pyvisa `TCPIP::…::5025::SOCKET` resource
   (`_configure_vna`, `vna.py:89`) and holds it for the object's life.
   Sweep parameters are pushed once at connect + `setup()`; the setters
   cache values and **skip re-writing when unchanged**
   (e.g. `if self._fstart == value: return`, `vna.py:127`). Therefore a
   freshly-restarted instrument left with a reused `VNA` object would be
   **unconfigured** — you cannot just swap the dead socket back in.
3. **`measure_s11` is only ever called panda-side**, always on the same
   host as `cmtvna.service`. Call sites: `PandaClient.vna_loop`
   (client.py:691), `PandaClient.run_calibration_sequence`
   (client.py:589), `scripts/vna_position_sweep.py` (grid burst),
   `scripts/vna_manual.py` (interactive). Each has a natural enclosing
   block.
4. **`init_VNA` runs in `PandaClient.__init__`** (client.py:118), so a
   client today cannot exist without the service being up.
5. **eigsep-field mechanics:** the panda enables+starts the unit at first
   boot via `_cmd_apply_role` → `systemctl enable --now cmtvna`
   (cli.py:946), and `eigsep-panda.target` also lists it in `Wants=`.
   The services-drift checker compares only `[Service]`
   User/Group/Restart/Type + ExecStart argv0 basename + tag alignment; it
   **explicitly ignores `[Install] WantedBy`** (check_services_drift.py,
   comment lines 55–58).

## Goals

- `cmtvna.service` stopped whenever no S11 measurement is in flight.
- Transparent to callers: `measure_s11` "just works" — the machinery
  brings the service up, connects, configures, measures, then tears down.
- Cold-start (xvfb + binary boot + reconfigure) paid **once per window**,
  not per sweep, so bursts and position sweeps stay cheap.
- No change to the S11 data contract or file headers.

## Non-goals

- No idle-timeout watchdog / background supervisor (rejected in favor of
  explicit session windows).
- No socket-activation of the proprietary binary (it does not support
  systemd fd-passing and would still busy-loop once up).
- No support for `PandaClient` running on a different host than
  `cmtvna.service` (see Risks — flagged in-code, not built).

## Design overview

Introduce an explicit **VNA session** that owns the service+connection
lifecycle, and make the connection lazy:

```python
with client.vna_session():          # start service, wait ready, init_VNA()
    with client.coord.switch_section():
        client.measure_s11("ant")
        client.measure_s11("rec")
# session exit: close socket, stop service
```

Because each session builds a **fresh `VNA`** via the existing
`init_VNA()` (new socket **and** full `setup()` re-push), constraint #2
is sidestepped entirely — no reconnect logic, no `cmt_vna` internals
change required.

## Detailed design

### `eigsep_observing` (bulk of the work)

1. **Lazy VNA.** Remove the `init_VNA()` call from `PandaClient.__init__`
   (client.py:118). `self.vna` starts `None`. Everything else in
   `__init__` (the `_switch` wiring, heartbeat, RFANT force-safe) is
   independent of the VNA and stays.

2. **`PandaClient.vna_session()` context manager:**
   - **enter:** `_start_cmtvna()` → wait-until-ready → `self.init_VNA()`.
   - **yield.**
   - **exit (always, even on exception):** close the pyvisa resource
     (`self.vna.s.close()`), set `self.vna = None`, `_stop_cmtvna()`.
   - Re-entrant guard: nested `vna_session()` calls share the outer
     session (refcount) so a burst script that opens a session and calls
     helpers which also open one don't stop the service early.

3. **Service control helper** (new small module, e.g.
   `vna_service.py`): `start()` / `stop()` shell out to
   `systemctl start|stop cmtvna.service`. Runs locally (constraint #3),
   authorized by the polkit rule below — no `sudo`. Non-zero exit
   surfaces as a clear error via `_error_with_status`.

4. **Readiness probe** `_wait_vna_ready(timeout≈60s)`: after start, poll
   by opening a throwaway pyvisa socket and querying `*IDN?` with a short
   per-attempt timeout + backoff, until it returns the R60 id or the cap
   is hit. TCP-accept alone is insufficient — the server accepts before
   the instrument is ready. On timeout: raise, stop the service, surface
   via status. (The 60s cap is a starting value; tune from the measured
   cold-start in the de-risk step.)

5. **Call-site wraps** — the session wraps **outside** `switch_section`
   so the ~seconds of warm-up don't hold the RF-switch lock:
   - `vna_loop`: wrap the **body of the while loop** (session → switch
     section → ant+rec), so the service is down during the long
     inter-iteration wait.
   - `run_calibration_sequence`: wrap its VNA block.
   - `scripts/vna_position_sweep.py`: **one** session around the whole
     grid loop (the burst stays warm).
   - `scripts/vna_manual.py`: one session around the interactive block.
   - `build_vna_subsystem` (vna.py:147): move the `VNA(...)` + `setup()`
     into a session-managed lifecycle so bring-up scripts inherit it.

6. **Outside-session guard.** `measure_s11` / `PandaClient.measure_s11`
   raise a clear, actionable error if `self.vna is None` (i.e. called
   with no open session) rather than silently auto-starting — keeps the
   cold-start cost intentional and visible. Message names `vna_session()`.

### `eigsep-field` (this repo)

1. **New `activation = "on-demand"`** value for `[services.*]`: unit is
   installed and present on the image but neither `enable-always` nor
   `_apply-role` enables/starts it. Set `[services.cmtvna].activation =
   "on-demand"` (drop `role` requirement, or keep `role = "panda"` purely
   as a "which Pi ships it" hint — decide during impl).
2. **`_cmd_apply_role`** (cli.py:~942): skip `on-demand` services exactly
   as it already skips non-`role` ones. `enable-always` already skips
   them (not `always`).
3. **`eigsep-panda.target`**: remove `cmtvna.service` from `Wants=`
   (systemd/eigsep-panda.target:3) so the target no longer pulls it.
4. **Unit file:** no `[Service]` change (keeps drift green). Optionally
   drop `PartOf=eigsep-panda.target` so a target restart can't kill an
   in-flight sweep — nice-to-have, not required. `[Install] WantedBy`
   left as-is (inert once nobody runs `systemctl enable cmtvna`; and
   ignored by the drift checker).
5. **Doctor / `services` command** (cli.py `_check_services` ~318,
   `services` ~434, `unit_health`): teach them that `on-demand` units are
   healthy when **present and not failed**, regardless of active/enabled —
   so a stopped `cmtvna.service` is reported "present (on-demand)" and
   never a red failure.
6. **Polkit rule**, delivered by the image (drop a file in
   `/etc/polkit-1/rules.d/`, staged like the other image files):
   ```javascript
   // 49-eigsep-cmtvna.rules — let 'eigsep' manage only cmtvna.service
   polkit.addRule(function(action, subject) {
     if (action.id == "org.freedesktop.systemd1.manage-units" &&
         action.lookup("unit") == "cmtvna.service" &&
         subject.user == "eigsep") {
       return polkit.Result.YES;
     }
   });
   ```
   Lets the panda_observe process `systemctl start/stop cmtvna.service`
   passwordless without a `sudo` shell-out. (Fallback: a scoped
   `NOPASSWD` sudoers line if Trixie's polkit build misbehaves.)
7. **Docs:** update `docs/operator/` panda runbook (the service is now
   operator/observe-managed, not always-on) and the CLAUDE.md
   "adding a systemd service" section to document the `on-demand`
   activation value.

### `cmt_vna` (optional)

- Add a `VNA.close()` that closes `self.s` and clears cached state, so
  eigsep_observing calls `vna.close()` instead of reaching into
  `vna.s.close()`. Purely cosmetic; not required for correctness.

## Ordering / interaction notes

- **Session ⊃ switch_section**, never the reverse: warm-up must not hold
  `coord.switch_section()`.
- The `_switch` RF-switch path is Redis/PicoProxy-mediated and
  independent of `cmtvna` — unaffected.
- `vna_loop`'s existing try/except around the VNA block already logs and
  continues on failure (corr data is sacred). A failed
  start/ready/measure surfaces through that same posture; the `finally`
  in `vna_session()` still stops the service so a failed sweep never
  leaves it running.

## Testing

- **eigsep_observing (unit):** `DummyVNA` + a fake service-control
  (record start/stop calls) to assert: session enter starts before
  connect and exit stops after close; nested sessions refcount; an
  exception mid-measure still stops the service; `measure_s11` outside a
  session raises. Readiness probe: fake `*IDN?` failing N times then
  succeeding.
- **eigsep-field (unit):** `activation="on-demand"` is skipped by
  `_apply-role` and `enable-always`; doctor reports a stopped on-demand
  unit as healthy; drift check stays green after the target/manifest
  edits; polkit rule file is staged into the image tree.
- **On-Pi manual:** cold-start timing; a full `vna_loop` iteration brings
  the service up then down; CPU/temp return to baseline between
  measurements; a burst (position sweep) keeps it up for one window.

## Rollout / de-risk (do first)

1. On the panda: `sudo systemctl stop cmtvna` and watch `htop` — confirm
   CPU/temp drop and nothing else wedges. Validates the whole premise.
2. Time a cold start (`systemctl start cmtvna` → first successful
   `*IDN?`) to set the readiness timeout.
3. Land eigsep_observing behind the session (VNA still constructed each
   session) with the service left always-on — verify sessions work while
   the service is up.
4. Flip eigsep-field to `on-demand` + polkit; verify end-to-end on the
   panda.

## Risks & open questions

- **Cold-start latency** adds seconds of delay to the first measurement
  in a window. Acceptable for hourly/burst cadence; quantify in step 2.
- **Host-locality assumption** (constraint #3): if `PandaClient` ever
  runs off-panda, local `systemctl` breaks. Add an in-code comment; a
  future fix would route start/stop through Redis like the RF switch.
- **Polkit on Trixie:** confirm the `.rules` (JS) format is honored by
  the image's polkit build; fall back to scoped sudoers if not.
- **fd leak:** building a fresh `VNA` per session must close the previous
  pyvisa resource — covered by the session `finally`, but verify no
  socket leak across many iterations in the on-Pi test.

## Cross-repo coordination

Per this repo's CLAUDE.md, the change spans siblings. File a
`contract-change`-style tracking issue here, and land the two PRs
together (eigsep_observing behavior + eigsep-field service model) so the
image and the observe code flip in lockstep — an on-demand image with an
old observe build would never start the service, and a new observe build
on an always-on image would stop it after each session but pay no CPU win
until the image flips. Bump `[services.cmtvna].tag` / `[packages.eigsep-vna]`
only if the `cmt_vna.close()` change ships.
