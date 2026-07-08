# eigsep_observing — On-Demand VNA Session Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Repo:** `/home/eigsep/eigsep/eigsep_observing` (NOT eigsep-field — this plan is
> stored in the eigsep-field coordination repo but executed in eigsep_observing).
> Start from a clean branch off `main`, e.g. `git checkout main && git pull &&
> git checkout -b feat/vna-on-demand-session`.
>
> **Companion spec:** `eigsep-field/docs/superpowers/specs/2026-07-06-cmtvna-on-demand-service-design.md`
> **Companion plan (land together):** `2026-07-06-eigsep-field-cmtvna-on-demand-service-model.md`

**Goal:** Stop the CPU-pegging `cmtvna.service` between S11 measurements by making the VNA connection lazy and lifecycle-managed: a VNA session starts the service, waits for readiness, builds a fresh `cmt_vna.VNA`, measures, then closes the socket and stops the service.

**Architecture:** A new `vna_service` module shells out to `systemctl start/stop cmtvna.service` (with a `sudo -n` fallback matching the image's sudoers drop-in) and probes readiness with a SCPI `*IDN?`. `PandaClient` gains a refcounted `vna_open()`/`vna_close()`/`vna_session()` trio; `__init__` no longer eagerly connects. Every `measure_s11` call site (two client methods, two scripts) is wrapped in a session, sized so the ~5.5s cold start is paid once per window (once per `vna_interval` for `vna_loop`, once per grid for the position sweep). The dummy/CI path skips `systemctl` entirely via a class flag.

**Tech Stack:** Python ≥3.10, pyvisa (already a `cmt_vna` dep), pytest + pytest-xdist + fakeredis (`eigsep_redis.testing.DummyTransport`), `cmt_vna.testing.DummyVNA`, `eigsep_observing.testing.DummyPandaClient`.

## Global Constraints

- Ruff, line length **79**; code must pass `uvx ruff check .` and `uvx ruff format --check .`.
- Tests run under `pytest-xdist` (`-n auto`) — every test must be isolation-safe (no shared global state, no reliance on ordering).
- Per-test timeout **60s** (`pytest-timeout`).
- New unit tests go in `tests/test_*.py`; the wheel-shipped producer contract tests live in `src/eigsep_observing/contract_tests/`.
- Shared fixtures already exist in `tests/conftest.py`: `transport` (`DummyTransport()`), `client` (`DummyPandaClient`, cfg has `use_vna=False`), `dummy_cfg`, `module_tmpdir`.
- **There is no existing `subprocess`/`systemctl` usage in the repo** — this plan introduces the first; tests monkeypatch it.
- Cold start measured at a consistent **~5.5s** on the panda → readiness cap **30s**.
- Never call `systemctl` on the dummy/CI path (no service exists there).

---

## File Structure

- **Create** `src/eigsep_observing/vna_service.py` — `UNIT`, `start()`, `stop()`, `wait_ready(ip, port, *, timeout=30.0, poll_interval=0.5)`. The only module that shells out to `systemctl` / probes the socket. No Redis, no client state.
- **Modify** `src/eigsep_observing/client.py` — lazy VNA in `__init__`; add `vna_enabled` property, `_manage_vna_service` flag, `vna_open()`, `vna_close()`, `vna_session()`; rewrite `vna_loop` and `run_calibration_sequence` VNA blocks to open a session.
- **Modify** `src/eigsep_observing/vna.py` — sharpen the `vna is None` error in `measure_s11`; make `build_vna_subsystem` build the VNA through a session-style lifecycle (start service unless dummy) and have its `cleanup()` stop the service.
- **Modify** `src/eigsep_observing/testing/client.py` — `DummyPandaClient._manage_vna_service = False` (keep the existing `init_VNA` DummyVNA override).
- **Modify** `scripts/vna_manual.py` — wrap the `_repl` loop in a session (or the subsystem's service lifecycle).
- **Modify** `src/eigsep_observing/scripts/vna_position_sweep.py` — one session around the grid loop; change the `client.vna is None` precheck to `not client.vna_enabled`.
- **Modify** `src/eigsep_observing/scripts/no_switch_observation.py` — change the `client.vna is None` precheck to `not client.vna_enabled` (the session is opened inside `run_calibration_sequence`).
- **Create** `tests/test_vna_service.py` — unit tests for the new module.
- **Modify** `tests/test_client.py`, `src/eigsep_observing/contract_tests/test_producer_contracts.py` — wrap `use_vna=True` `measure_s11` calls in `vna_session()`.

---

## Task 1: `vna_service` module (start / stop / readiness)

**Files:**
- Create: `src/eigsep_observing/vna_service.py`
- Test: `tests/test_vna_service.py`

**Interfaces:**
- Produces: `vna_service.UNIT` (str `"cmtvna.service"`); `vna_service.start() -> None`; `vna_service.stop() -> None`; `vna_service.wait_ready(ip: str, port: int, *, timeout: float = 30.0, poll_interval: float = 0.5) -> str` (returns the `*IDN?` string; raises `TimeoutError` on cap, `RuntimeError` if `systemctl` fails).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_vna_service.py`:

```python
import subprocess

import pytest

from eigsep_observing import vna_service


def test_start_runs_systemctl_start(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    vna_service.start()
    assert calls == [
        ["systemctl", "start", "--no-ask-password", "cmtvna.service"]
    ]


def test_start_falls_back_to_sudo(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        rc = 0 if cmd[0] == "sudo" else 1
        return subprocess.CompletedProcess(cmd, rc, "", "boom")

    monkeypatch.setattr(subprocess, "run", fake_run)
    vna_service.start()
    assert calls[0][0] == "systemctl"
    assert calls[1][:2] == ["sudo", "-n"]


def test_start_raises_when_both_fail(monkeypatch):
    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, "", "nope")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match="start cmtvna.service failed"):
        vna_service.start()


def test_wait_ready_returns_idn_after_retries(monkeypatch):
    attempts = {"n": 0}

    class FakeResource:
        read_termination = None
        timeout = None

        def query(self, _msg):
            return "CMT,R60,123,1.7.1\n"

        def close(self):
            pass

    class FakeRM:
        def open_resource(self, _addr):
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise OSError("connection refused")
            return FakeResource()

    monkeypatch.setattr(
        vna_service.pyvisa, "ResourceManager", lambda _b: FakeRM()
    )
    monkeypatch.setattr(vna_service.time, "sleep", lambda _s: None)

    idn = vna_service.wait_ready("127.0.0.1", 5025, timeout=30.0)
    assert idn == "CMT,R60,123,1.7.1"
    assert attempts["n"] == 3


def test_wait_ready_times_out(monkeypatch):
    clock = {"t": 0.0}

    class FakeRM:
        def open_resource(self, _addr):
            raise OSError("refused")

    monkeypatch.setattr(
        vna_service.pyvisa, "ResourceManager", lambda _b: FakeRM()
    )
    monkeypatch.setattr(vna_service.time, "sleep", lambda _s: None)

    def fake_monotonic():
        clock["t"] += 1.0
        return clock["t"]

    monkeypatch.setattr(vna_service.time, "monotonic", fake_monotonic)
    with pytest.raises(TimeoutError, match="cmtvna not ready"):
        vna_service.wait_ready("127.0.0.1", 5025, timeout=2.0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_vna_service.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'eigsep_observing.vna_service'`.

- [ ] **Step 3: Write the module**

Create `src/eigsep_observing/vna_service.py`:

```python
"""On-demand control of ``cmtvna.service`` (panda-side).

The CMT R60 driver binary runs as a systemd service in socket-server
mode and busy-loops at ~300% CPU whenever it is up, so the field stack
keeps it stopped and starts it only around an S11 measurement window.
This module is the thin start/stop/readiness layer; the session
lifecycle lives in :meth:`eigsep_observing.client.PandaClient.vna_session`
and :func:`eigsep_observing.vna.build_vna_subsystem`.

Panda-only: the caller runs on the same host as the service (``vna_ip``
is ``127.0.0.1``). ``start``/``stop`` shell out to ``systemctl`` and fall
back to ``sudo -n`` — the field image ships a sudoers drop-in granting
the ``eigsep`` user passwordless start/stop of exactly this unit (mirrors
the flash-picos ``systemctl``-then-``sudo -n`` fallback).
"""

import logging
import subprocess
import time

import pyvisa

UNIT = "cmtvna.service"

logger = logging.getLogger(__name__)


def _systemctl(action):
    """Run ``systemctl <action> --no-ask-password cmtvna.service``.

    Try plain ``systemctl`` first (works as root / when already
    permitted), then ``sudo -n`` (passwordless via the image sudoers
    drop-in). Raise ``RuntimeError`` with both captured outputs if both
    fail.
    """
    base = ["systemctl", action, "--no-ask-password", UNIT]
    first = subprocess.run(base, capture_output=True, text=True)
    if first.returncode == 0:
        return
    second = subprocess.run(
        ["sudo", "-n", *base], capture_output=True, text=True
    )
    if second.returncode == 0:
        return
    raise RuntimeError(
        f"{action} {UNIT} failed: "
        f"{(first.stderr or first.stdout).strip()!r} then "
        f"{(second.stderr or second.stdout).strip()!r}"
    )


def start():
    """Start ``cmtvna.service``. Idempotent (systemctl no-ops if active)."""
    logger.info("Starting %s", UNIT)
    _systemctl("start")


def stop():
    """Stop ``cmtvna.service`` to release the CPU."""
    logger.info("Stopping %s", UNIT)
    _systemctl("stop")


def wait_ready(ip, port, *, timeout=30.0, poll_interval=0.5):
    """Block until the cmtvna socket answers ``*IDN?``; raise on timeout.

    The socket server accepts TCP before the instrument is ready, so we
    probe at the SCPI level. Cold start is a consistent ~5.5s on the
    panda; the 30s default is ~5x headroom.

    Returns the trimmed ``*IDN?`` response. Raises ``TimeoutError`` if
    the instrument never answers within ``timeout`` seconds.
    """
    rm = pyvisa.ResourceManager("@py")
    addr = f"TCPIP::{ip}::{port}::SOCKET"
    deadline = time.monotonic() + timeout
    last_exc = None
    while time.monotonic() < deadline:
        try:
            res = rm.open_resource(addr)
            res.read_termination = "\n"
            res.timeout = 2000
            idn = res.query("*IDN?\n")
            res.close()
            logger.info("%s ready: %s", UNIT, idn.strip())
            return idn.strip()
        except Exception as exc:  # pyvisa raises many error types
            last_exc = exc
            time.sleep(poll_interval)
    raise TimeoutError(
        f"cmtvna not ready on {ip}:{port} after {timeout}s "
        f"(last error: {last_exc})"
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_vna_service.py -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Lint**

Run: `uvx ruff check src/eigsep_observing/vna_service.py tests/test_vna_service.py && uvx ruff format --check src/eigsep_observing/vna_service.py tests/test_vna_service.py`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add src/eigsep_observing/vna_service.py tests/test_vna_service.py
git commit -m "feat(vna): add vna_service start/stop/wait_ready for on-demand cmtvna"
```

---

## Task 2: Lazy VNA + `vna_open`/`vna_close`/`vna_session` on PandaClient

**Files:**
- Modify: `src/eigsep_observing/client.py` (`__init__` lines 117-121; add methods after `init_VNA`)
- Modify: `src/eigsep_observing/vna.py` (`measure_s11` `vna is None` message, ~line 329)
- Test: `tests/test_client.py` (append new tests)

**Interfaces:**
- Consumes: `vna_service.start/stop/wait_ready` (Task 1).
- Produces: `PandaClient.vna_enabled` (bool property); `PandaClient._manage_vna_service` (class attr, default `True`); `PandaClient.vna_open()`; `PandaClient.vna_close()`; `PandaClient.vna_session()` (contextmanager). After construction `self.vna is None` until a session opens; `self._vna_depth` (int) refcounts nesting.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_client.py` (module already imports `DummyVNA`, `DummyPandaClient`, `pytest`):

```python
def test_vna_lazy_none_until_session(transport, dummy_cfg):
    cfg = dict(dummy_cfg)
    cfg["use_vna"] = True
    client = DummyPandaClient(transport, cfg=cfg)
    try:
        assert client.vna is None  # lazy: not built at construction
        assert client.vna_enabled is True
        with client.vna_session():
            assert isinstance(client.vna, DummyVNA)
        assert client.vna is None  # torn down on exit
    finally:
        client.stop()


def test_vna_session_nests_without_early_teardown(transport, dummy_cfg):
    cfg = dict(dummy_cfg)
    cfg["use_vna"] = True
    client = DummyPandaClient(transport, cfg=cfg)
    try:
        with client.vna_session():
            outer = client.vna
            with client.vna_session():
                assert client.vna is outer  # inner reuses the object
            assert client.vna is outer  # still alive after inner exit
        assert client.vna is None
    finally:
        client.stop()


def test_vna_open_rejected_when_disabled(client):
    # default fixture cfg has use_vna=False
    assert client.vna_enabled is False
    with pytest.raises(RuntimeError, match="use_vna=false"):
        client.vna_open()


def test_vna_session_starts_and_stops_service(transport, dummy_cfg, monkeypatch):
    # Force the real (service-managed) path even on the dummy client.
    cfg = dict(dummy_cfg)
    cfg["use_vna"] = True
    client = DummyPandaClient(transport, cfg=cfg)
    monkeypatch.setattr(client, "_manage_vna_service", True)
    events = []
    from eigsep_observing import vna_service

    monkeypatch.setattr(vna_service, "start", lambda: events.append("start"))
    monkeypatch.setattr(vna_service, "stop", lambda: events.append("stop"))
    monkeypatch.setattr(
        vna_service, "wait_ready", lambda ip, port, **k: events.append("ready")
    )
    try:
        with client.vna_session():
            assert events == ["start", "ready"]
        assert events == ["start", "ready", "stop"]
    finally:
        client.stop()


def test_vna_session_stops_service_on_ready_failure(
    transport, dummy_cfg, monkeypatch
):
    cfg = dict(dummy_cfg)
    cfg["use_vna"] = True
    client = DummyPandaClient(transport, cfg=cfg)
    monkeypatch.setattr(client, "_manage_vna_service", True)
    events = []
    from eigsep_observing import vna_service

    monkeypatch.setattr(vna_service, "start", lambda: events.append("start"))
    monkeypatch.setattr(vna_service, "stop", lambda: events.append("stop"))

    def boom(ip, port, **k):
        raise TimeoutError("not ready")

    monkeypatch.setattr(vna_service, "wait_ready", boom)
    try:
        with pytest.raises(TimeoutError):
            client.vna_open()
        assert events == ["start", "stop"]  # service stopped on failure
        assert client._vna_depth == 0
    finally:
        client.stop()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_client.py -q -k "vna_lazy or vna_session or vna_open"`
Expected: FAIL — `AttributeError: 'DummyPandaClient' object has no attribute 'vna_enabled'` / `vna_open`.

- [ ] **Step 3: Make `__init__` lazy**

In `src/eigsep_observing/client.py`, replace lines 117-121:

```python
        if self.cfg.get("use_vna", False):
            self.init_VNA()
        else:
            self.vna = None
            self.logger.info("VNA not initialized")
```

with:

```python
        # VNA is lazy: cmtvna.service busy-loops the CPU, so it runs
        # on-demand. vna_open()/vna_session() start the service, wait for
        # readiness, and build a fresh VNA; the service is stopped on
        # close. self.vna is None between sessions. See
        # eigsep_observing.vna_service.
        self.vna = None
        self._vna_enabled = self.cfg.get("use_vna", False)
        self._vna_depth = 0
        if not self._vna_enabled:
            self.logger.info("VNA disabled (use_vna=false)")
```

- [ ] **Step 4: Add the session methods and import**

At the top of `client.py`, add to the existing imports (a `from . import ...` line already imports submodules; add this near them):

```python
from . import vna_service
```

Immediately after the `init_VNA` method (currently ends at line 376), add:

```python
    _manage_vna_service = True

    @property
    def vna_enabled(self):
        """True if the config enabled the VNA (``use_vna``)."""
        return self._vna_enabled

    def vna_open(self):
        """Start cmtvna.service, wait for readiness, and build the VNA.

        Refcounted: the service starts and the VNA is built on the
        outermost open; inner opens only bump the depth. On the outermost
        open, a readiness/build failure stops the service again before
        re-raising, so a failed open never leaves the CPU pegged. Raises
        RuntimeError if the config disabled the VNA.
        """
        if not self._vna_enabled:
            raise RuntimeError(
                "Cannot open a VNA session: VNA disabled in config "
                "(use_vna=false)."
            )
        if self._vna_depth == 0:
            if self._manage_vna_service:
                vna_service.start()
            try:
                if self._manage_vna_service:
                    vna_service.wait_ready(
                        self.cfg["vna_ip"], self.cfg["vna_port"]
                    )
                self.init_VNA()
            except Exception:
                if self._manage_vna_service:
                    try:
                        vna_service.stop()
                    except Exception:
                        self.logger.warning(
                            "cmtvna stop after failed open also failed",
                            exc_info=True,
                        )
                raise
        self._vna_depth += 1

    def vna_close(self):
        """Tear down the VNA and stop cmtvna.service on the outermost close."""
        if self._vna_depth == 0:
            return
        self._vna_depth -= 1
        if self._vna_depth > 0:
            return
        vna = self.vna
        self.vna = None
        sock = getattr(vna, "s", None)
        if sock is not None and hasattr(sock, "close"):
            try:
                sock.close()
            except Exception:
                self.logger.warning("VNA socket close failed", exc_info=True)
        if self._manage_vna_service:
            try:
                vna_service.stop()
            except Exception:
                self.logger.warning("cmtvna stop failed", exc_info=True)

    @contextmanager
    def vna_session(self):
        """Context-managed VNA window: open on enter, close on exit.

        Wrap it OUTSIDE ``coord.switch_section()`` so the ~5.5s warm-up
        does not hold the RF-switch lock.
        """
        self.vna_open()
        try:
            yield
        finally:
            self.vna_close()
```

(`contextmanager` is already imported at `client.py:4`.)

- [ ] **Step 5: Sharpen the `measure_s11` error**

In `src/eigsep_observing/vna.py`, the `measure_s11` guard (~line 329) currently reads:

```python
    if vna is None:
        raise RuntimeError("VNA not initialized. Cannot execute VNA commands.")
```

Replace with:

```python
    if vna is None:
        raise RuntimeError(
            "VNA not initialized. Open a VNA session first "
            "(PandaClient.vna_open()/vna_session(), or "
            "build_vna_subsystem)."
        )
```

(The existing `match="VNA not initialized"` assertions still pass — it is a substring search.)

- [ ] **Step 6: Run the new + existing guard tests**

Run: `uv run pytest tests/test_client.py tests/test_vna_helper.py -q -k "vna_lazy or vna_session or vna_open or requires_initialized"`
Expected: PASS.

- [ ] **Step 7: Lint**

Run: `uvx ruff check src/eigsep_observing/client.py src/eigsep_observing/vna.py tests/test_client.py && uvx ruff format --check src/eigsep_observing/client.py src/eigsep_observing/vna.py tests/test_client.py`
Expected: no errors.

- [ ] **Step 8: Commit**

```bash
git add src/eigsep_observing/client.py src/eigsep_observing/vna.py tests/test_client.py
git commit -m "feat(vna): lazy VNA with refcounted vna_open/close/session on PandaClient"
```

---

## Task 3: Keep the dummy/CI path off systemctl + migrate existing VNA tests

**Files:**
- Modify: `src/eigsep_observing/testing/client.py` (add class flag)
- Modify: `tests/test_client.py` (wrap two `use_vna=True` measure calls)
- Modify: `src/eigsep_observing/contract_tests/test_producer_contracts.py` (wrap one call)

**Interfaces:**
- Consumes: `vna_session()` (Task 2).
- Produces: `DummyPandaClient._manage_vna_service = False` — the dummy client builds `DummyVNA` and never touches `systemctl`.

- [ ] **Step 1: Run the suite to see what lazy VNA broke**

Run: `uv run pytest tests/test_client.py src/eigsep_observing/contract_tests/test_producer_contracts.py -q`
Expected: FAILs in tests that set `use_vna=True` then call `measure_s11` without a session — they now raise `RuntimeError: VNA not initialized`. Confirm the failing tests are exactly:
`test_measure_s11_contract_violation_emits_on_both_channels`,
`test_measure_s11_clean_payload_does_not_send_status`,
`test_measure_s11_publishes_conforming_payload[ant|rec]`.
(Note any others the run reports; apply the same wrap.)

- [ ] **Step 2: Add the dummy service-skip flag**

In `src/eigsep_observing/testing/client.py`, inside `class DummyPandaClient(PandaClient):`, add the class attribute (put it directly under the docstring, before `__init__`):

```python
    # The dummy client uses DummyVNA and has no cmtvna.service; never
    # shell out to systemctl.
    _manage_vna_service = False
```

- [ ] **Step 3: Wrap the migrated measure calls**

In `tests/test_client.py`, in `test_measure_s11_contract_violation_emits_on_both_channels`, change:

```python
            caplog.set_level(logging.WARNING, logger="eigsep_observing.client")
            client.measure_s11("ant")
```

to:

```python
            caplog.set_level(logging.WARNING, logger="eigsep_observing.client")
            with client.vna_session():
                client.measure_s11("ant")
```

In `tests/test_client.py`, in `test_measure_s11_clean_payload_does_not_send_status`, change:

```python
        _arm_status_reader(client)
        client.measure_s11("ant")
        level, status = _status_reader(client).read(timeout=0.2)
```

to:

```python
        _arm_status_reader(client)
        with client.vna_session():
            client.measure_s11("ant")
        level, status = _status_reader(client).read(timeout=0.2)
```

In `src/eigsep_observing/contract_tests/test_producer_contracts.py` (~line 353-354), change:

```python
        client.measure_s11(mode)
```

to:

```python
        with client.vna_session():
            client.measure_s11(mode)
```

- [ ] **Step 4: Run the suite green**

Run: `uv run pytest tests/test_client.py src/eigsep_observing/contract_tests/test_producer_contracts.py -q`
Expected: PASS. If any other test failed in Step 1 with `VNA not initialized`, apply the identical `with client.vna_session():` wrap around its `measure_s11` call and re-run.

- [ ] **Step 5: Lint**

Run: `uvx ruff check src/eigsep_observing/testing/client.py tests/test_client.py src/eigsep_observing/contract_tests/test_producer_contracts.py && uvx ruff format --check src/eigsep_observing/testing/client.py tests/test_client.py src/eigsep_observing/contract_tests/test_producer_contracts.py`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add src/eigsep_observing/testing/client.py tests/test_client.py src/eigsep_observing/contract_tests/test_producer_contracts.py
git commit -m "test(vna): dummy client skips systemctl; wrap measure_s11 in sessions"
```

---

## Task 4: Wrap `vna_loop` in a per-iteration session

**Files:**
- Modify: `src/eigsep_observing/client.py` (`vna_loop`, lines 691-738)
- Test: `tests/test_client.py`

**Interfaces:**
- Consumes: `vna_session()`, `vna_enabled` (Task 2).
- Produces: `vna_loop` opens one session per iteration (service up only during the ant+rec block; down during the `vna_interval` wait). Exits promptly when `vna_enabled` is false.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_client.py`:

```python
def test_vna_loop_measures_then_stops(transport, dummy_cfg):
    cfg = dict(dummy_cfg)
    cfg["use_vna"] = True
    cfg["vna_interval"] = 0.05
    client = DummyPandaClient(transport, cfg=cfg)
    try:
        from eigsep_observing.keys import VNA_STREAM

        # Stop after the first iteration's measurements land.
        import threading

        def stopper():
            while client.transport.r.xlen(VNA_STREAM) < 2:
                pass
            client.stop_client.set()

        t = threading.Thread(target=stopper, daemon=True)
        t.start()
        client.vna_loop()  # returns once stop_client is set
        t.join(timeout=5)
        # ant + rec bundles were published in at least one session.
        assert client.transport.r.xlen(VNA_STREAM) >= 2
        # Session torn down on loop exit.
        assert client.vna is None
    finally:
        client.stop()
```

(Confirm the `VNA_STREAM` key name via `from eigsep_observing.keys import VNA_STREAM`; it is the stream `measure_s11` publishes to.)

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_client.py -q -k vna_loop_measures`
Expected: FAIL — currently `vna_loop` early-returns because `self.vna is None` (lazy), so nothing is published.

- [ ] **Step 3: Rewrite the `vna_loop` guard and wrap the body**

In `src/eigsep_observing/client.py`, change the guard at the top of `vna_loop` (lines 695-699):

```python
        if self.vna is None:
            self._warn_with_status(
                "VNA not initialized. Cannot execute VNA commands."
            )
            return
```

to:

```python
        if not self._vna_enabled:
            self._warn_with_status(
                "VNA disabled in config (use_vna=false); vna_loop exiting."
            )
            return
```

Then wrap the `with self.coord.switch_section():` block in a session. The loop body becomes (open a session around the existing switch_section; catch a failed session-open so the loop survives a service hiccup):

```python
        while not self.stop_client.is_set():
            try:
                with self.vna_session():
                    with self.coord.switch_section():
                        prev_mode = self._read_switch_mode_from_redis()
                        if prev_mode is None:
                            self._warn_with_status(
                                "rfswitch state unavailable in Redis; "
                                "defaulting post-VNA switch-back to RFANT."
                            )
                            prev_mode = "RFANT"
                        target_mode = prev_mode
                        try:
                            for mode in ["ant", "rec"]:
                                self.logger.info(
                                    f"Measuring S11 of {mode} with VNA"
                                )
                                self.measure_s11(mode)
                        except Exception as exc:
                            self._error_with_status(
                                f"VNA cycle aborted "
                                f"({type(exc).__name__}: {exc}); "
                                "recovering rfswitch to RFANT."
                            )
                            target_mode = "RFANT"
                        self.logger.info(
                            f"Switching rfswitch to {target_mode} "
                            f"(previous mode: {prev_mode})"
                        )
                        if not self._safe_switch(target_mode):
                            self._warn_with_status(
                                f"Failed to switch back to {target_mode}"
                            )
            except Exception as exc:
                self._error_with_status(
                    f"VNA session failed "
                    f"({type(exc).__name__}: {exc}); skipping this cycle."
                )
            self.stop_client.wait(self.cfg["vna_interval"])
```

(This preserves the existing inner try/except and switch-back logic verbatim; it only adds the outer `with self.vna_session():` and the outer `try/except` that keeps the loop alive if the service fails to start.)

- [ ] **Step 4: Run the new + existing vna_loop tests**

Run: `uv run pytest tests/test_client.py -q -k vna_loop`
Expected: PASS — including the existing `test_vna_loop_returns_when_vna_is_none` (default fixture has `use_vna=False`, so the new guard still returns promptly and `client.vna is None` still holds).

- [ ] **Step 5: Lint**

Run: `uvx ruff check src/eigsep_observing/client.py tests/test_client.py && uvx ruff format --check src/eigsep_observing/client.py tests/test_client.py`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add src/eigsep_observing/client.py tests/test_client.py
git commit -m "feat(vna): vna_loop opens a service session per iteration"
```

---

## Task 5: Wrap `run_calibration_sequence`'s VNA block in a session

**Files:**
- Modify: `src/eigsep_observing/client.py` (`run_calibration_sequence`, VNA block lines 631-652)
- Test: `tests/test_client.py`

**Interfaces:**
- Consumes: `vna_session()`, `vna_enabled` (Task 2).
- Produces: `run_calibration_sequence` opens one session around its ant+rec VNA block; the dwell phase (non-VNA) runs with the service down.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_client.py`:

```python
def test_run_calibration_sequence_uses_session(transport, dummy_cfg):
    cfg = dict(dummy_cfg)
    cfg["use_vna"] = True
    cfg["switch_schedule"] = {}  # skip dwell phase; test the VNA block
    client = DummyPandaClient(transport, cfg=cfg)
    try:
        from eigsep_observing.keys import VNA_STREAM

        assert client.run_calibration_sequence() is True
        assert client.transport.r.xlen(VNA_STREAM) >= 2  # ant + rec
        assert client.vna is None  # session closed after the block
    finally:
        client.stop()
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_client.py -q -k run_calibration_sequence_uses_session`
Expected: FAIL — the current code checks `if self.vna is None:` and warns/skips because the VNA is lazy, so nothing is published.

- [ ] **Step 3: Rewrite the VNA block**

In `src/eigsep_observing/client.py`, replace the VNA block of `run_calibration_sequence` (lines 631-652):

```python
        if self.vna is None:
            self._warn_with_status(
                "VNA not initialized; skipping VNA portion of calibration."
            )
        else:
            with self.coord.switch_section():
                try:
                    for mode in vna_modes:
                        if self.stop_client.is_set():
                            return False
                        self.logger.info(
                            f"Calibration: measuring S11 of {mode} with VNA"
                        )
                        self.measure_s11(mode)
                except Exception as exc:
                    self._error_with_status(
                        f"Calibration VNA cycle aborted "
                        f"({type(exc).__name__}: {exc})."
                    )
```

with:

```python
        if not self._vna_enabled:
            self._warn_with_status(
                "VNA disabled (use_vna=false); skipping VNA portion of "
                "calibration."
            )
        else:
            try:
                with self.vna_session():
                    with self.coord.switch_section():
                        try:
                            for mode in vna_modes:
                                if self.stop_client.is_set():
                                    return False
                                self.logger.info(
                                    f"Calibration: measuring S11 of "
                                    f"{mode} with VNA"
                                )
                                self.measure_s11(mode)
                        except Exception as exc:
                            self._error_with_status(
                                f"Calibration VNA cycle aborted "
                                f"({type(exc).__name__}: {exc})."
                            )
            except Exception as exc:
                self._error_with_status(
                    f"Calibration VNA session failed "
                    f"({type(exc).__name__}: {exc})."
                )
```

Note: the `return False` on `stop_client` inside the session still fires the context manager's `finally` (closing the VNA and stopping the service) on the way out — correct.

- [ ] **Step 4: Run the test**

Run: `uv run pytest tests/test_client.py -q -k "run_calibration"`
Expected: PASS (new test plus any existing `run_calibration_sequence` tests).

- [ ] **Step 5: Lint + commit**

```bash
uvx ruff check src/eigsep_observing/client.py tests/test_client.py && uvx ruff format --check src/eigsep_observing/client.py tests/test_client.py
git add src/eigsep_observing/client.py tests/test_client.py
git commit -m "feat(vna): run_calibration_sequence opens a service session for its VNA block"
```

---

## Task 6: `build_vna_subsystem` + `vna_manual` session lifecycle

**Files:**
- Modify: `src/eigsep_observing/vna.py` (`build_vna_subsystem`, lines 214-245)
- Modify: `scripts/vna_manual.py` (`main`, lines 191-199)
- Test: `tests/test_vna_helper.py` (append)

**Interfaces:**
- Consumes: `vna_service.start/stop/wait_ready` (Task 1).
- Produces: `build_vna_subsystem(..., dummy=False)` starts the service + waits ready before building the real `VNA`; its returned `cleanup()` stops the service. `dummy=True` skips all service management (unchanged behavior otherwise).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_vna_helper.py` (it already builds dummy subsystems; check its imports for `build_vna_subsystem`, `DummyTransport`, `dummy_cfg`):

```python
def test_build_vna_subsystem_real_manages_service(monkeypatch, dummy_cfg):
    from eigsep_redis.testing import DummyTransport
    from eigsep_observing import vna, vna_service
    from cmt_vna.testing import DummyVNA

    events = []
    monkeypatch.setattr(vna_service, "start", lambda: events.append("start"))
    monkeypatch.setattr(vna_service, "stop", lambda: events.append("stop"))
    monkeypatch.setattr(
        vna_service, "wait_ready", lambda ip, port, **k: events.append("ready")
    )
    # Build the real (non-dummy) subsystem but with the VNA class faked
    # so no real socket is opened.
    monkeypatch.setattr(vna, "VNA", DummyVNA)

    transport = DummyTransport()
    from eigsep_observing.testing import start_dummy_pico_manager

    mgr = start_dummy_pico_manager(transport)
    try:
        sub = vna.build_vna_subsystem(
            transport, dummy_cfg_vna(dummy_cfg), source="test", dummy=False
        )
        assert events == ["start", "ready"]
        sub.cleanup()
        assert events == ["start", "ready", "stop"]
    finally:
        mgr.stop()


def dummy_cfg_vna(dummy_cfg):
    cfg = dict(dummy_cfg)
    cfg["use_vna"] = True
    return cfg
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_vna_helper.py -q -k build_vna_subsystem_real_manages_service`
Expected: FAIL — `events == []` (no service management in `build_vna_subsystem` yet).

- [ ] **Step 3: Add service management to `build_vna_subsystem`**

In `src/eigsep_observing/vna.py`, add the import near the top (with the other `from .` imports):

```python
from . import vna_service
```

Change the build block (lines 214-234) so the real path starts+waits the service, and the dummy path does not. Replace:

```python
    manager = None
    vna_cls = VNA
    if dummy:
        from cmt_vna.testing import DummyVNA
        from eigsep_observing.testing import start_dummy_pico_manager

        vna_cls = DummyVNA
        manager = start_dummy_pico_manager(transport)

    vna = vna_cls(
        ip=cfg["vna_ip"],
        port=cfg["vna_port"],
        timeout=cfg["vna_timeout"],
        switch_fn=switch_fn,
    )
```

with:

```python
    manager = None
    vna_cls = VNA
    if dummy:
        from cmt_vna.testing import DummyVNA
        from eigsep_observing.testing import start_dummy_pico_manager

        vna_cls = DummyVNA
        manager = start_dummy_pico_manager(transport)
    else:
        # Real hardware: bring cmtvna.service up and wait for the R60
        # before opening the socket. cleanup() stops it again.
        vna_service.start()
        vna_service.wait_ready(cfg["vna_ip"], cfg["vna_port"])

    vna = vna_cls(
        ip=cfg["vna_ip"],
        port=cfg["vna_port"],
        timeout=cfg["vna_timeout"],
        switch_fn=switch_fn,
    )
```

And extend `cleanup()` (lines 236-238) to stop the service on the real path:

```python
    def cleanup():
        if manager is not None:
            manager.stop()
        if not dummy:
            try:
                vna_service.stop()
            except Exception:
                logger.warning("cmtvna stop failed", exc_info=True)
```

- [ ] **Step 4: Wrap `vna_manual`'s REPL in the subsystem lifecycle**

`scripts/vna_manual.py` `main` already calls `subsystem.cleanup()` in a `finally` (line 199), and Task 6 made `cleanup()` stop the service. Because `build_vna_subsystem` now starts the service at build time, `main` needs no session wrapper — the whole REPL runs inside one service window (build → `_repl` → `cleanup`). Confirm the existing structure (lines 191-199) already provides this:

```python
    subsystem = build_vna_subsystem(
        transport, cfg, source="vna_manual", dummy=args.dummy
    )
    with run_tag.session(transport, "vna_manual"):
        try:
            _print_banner(cfg, args.save_dir)
            _repl(subsystem, cfg, transport, args.save_dir)
        finally:
            subsystem.cleanup()
```

No code change is required in `vna_manual.py` — but add a one-line comment above `build_vna_subsystem` documenting that it now starts `cmtvna.service` and `cleanup()` stops it:

```python
    # build_vna_subsystem starts cmtvna.service (real mode) and its
    # cleanup() stops it, so the whole REPL runs in one service window.
    subsystem = build_vna_subsystem(
        transport, cfg, source="vna_manual", dummy=args.dummy
    )
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_vna_helper.py tests/test_record_vna.py -q`
Expected: PASS (dummy subsystems skip service management, so `test_record_vna.py` — which builds `dummy=True` — is unaffected; the new real-path test passes).

- [ ] **Step 6: Lint + commit**

```bash
uvx ruff check src/eigsep_observing/vna.py scripts/vna_manual.py tests/test_vna_helper.py && uvx ruff format --check src/eigsep_observing/vna.py scripts/vna_manual.py tests/test_vna_helper.py
git add src/eigsep_observing/vna.py scripts/vna_manual.py tests/test_vna_helper.py
git commit -m "feat(vna): build_vna_subsystem manages cmtvna.service on the real path"
```

---

## Task 7: `vna_position_sweep` — one session around the grid + precheck fix

**Files:**
- Modify: `src/eigsep_observing/scripts/vna_position_sweep.py` (precheck line 114-117; grid loop lines 131-147)
- Test: `tests/test_motor_scripts.py`

**Interfaces:**
- Consumes: `vna_enabled` (Task 2), `vna_session()` (Task 2).
- Produces: the sweep opens exactly one `vna_session()` around the whole grid loop (service warm across the burst); the pre-flight check uses `client.vna_enabled` (the VNA object is lazily `None` at that point).

- [ ] **Step 1: Read the existing precheck test**

Run: `uv run pytest tests/test_motor_scripts.py -q -k vna_position` (observe current pass/fail and the assertion around the `client.vna is None` precheck near test_motor_scripts.py:407). This tells you which test asserts the "VNA not initialized" pre-flight message so you can update its expectation.

- [ ] **Step 2: Fix the precheck**

In `src/eigsep_observing/scripts/vna_position_sweep.py`, change (lines 114-117):

```python
            if client.vna is None:
                raise RuntimeError(
                    "VNA not initialized; check vna config block."
                )
```

to:

```python
            if not client.vna_enabled:
                raise RuntimeError(
                    "VNA disabled (use_vna=false); check vna config block."
                )
```

- [ ] **Step 3: Wrap the grid loop in one session**

In the same file, wrap the grid loop (lines 131-147). Change:

```python
            client.motor_client.set_delay()
            client.motor_client.halt()
            client.motor_client.home()
            for idx, (az, el) in enumerate(grid):
                if client.stop_client.is_set():
                    logger.info("stop_client set; aborting sweep")
                    break
                logger.info(
                    f"[{idx + 1}/{len(grid)}] move_to az={az}, el={el}"
                )
                client.motor_client.move_to(az_deg=az, el_deg=el)
                if settle_s > 0 and client.stop_client.wait(settle_s):
                    break
                with client.coord.switch_section():
                    for mode in ("ant", "rec"):
                        logger.info(
                            f"[{idx + 1}/{len(grid)}] measure_s11({mode!r})"
                        )
                        client.measure_s11(mode)
            client.motor_client.home()
```

to (note the new `with client.vna_session():` wrapping the whole `for` loop; the per-position `switch_section` stays inside it):

```python
            client.motor_client.set_delay()
            client.motor_client.halt()
            client.motor_client.home()
            # One service window for the whole burst: start cmtvna once,
            # keep it warm across every grid point, stop it after.
            with client.vna_session():
                for idx, (az, el) in enumerate(grid):
                    if client.stop_client.is_set():
                        logger.info("stop_client set; aborting sweep")
                        break
                    logger.info(
                        f"[{idx + 1}/{len(grid)}] move_to az={az}, el={el}"
                    )
                    client.motor_client.move_to(az_deg=az, el_deg=el)
                    if settle_s > 0 and client.stop_client.wait(settle_s):
                        break
                    with client.coord.switch_section():
                        for mode in ("ant", "rec"):
                            logger.info(
                                f"[{idx + 1}/{len(grid)}] "
                                f"measure_s11({mode!r})"
                            )
                            client.measure_s11(mode)
            client.motor_client.home()
```

- [ ] **Step 4: Update the precheck test expectation**

If Step 1 showed a test asserting the old `"VNA not initialized"` pre-flight message for this script, update its expected substring to `"VNA disabled"` (match the new message). Run `uv run pytest tests/test_motor_scripts.py -q -k vna_position` and fix any assertion that still expects the old string or that fails because the VNA is now lazily `None` (the dummy sweep path builds `DummyVNA` inside the session, so `client.measure_s11` succeeds).

- [ ] **Step 5: Run the script tests**

Run: `uv run pytest tests/test_motor_scripts.py -q`
Expected: PASS.

- [ ] **Step 6: Lint + commit**

```bash
uvx ruff check src/eigsep_observing/scripts/vna_position_sweep.py tests/test_motor_scripts.py && uvx ruff format --check src/eigsep_observing/scripts/vna_position_sweep.py tests/test_motor_scripts.py
git add src/eigsep_observing/scripts/vna_position_sweep.py tests/test_motor_scripts.py
git commit -m "feat(vna): position sweep runs the whole grid in one service window"
```

---

## Task 8: `no_switch_observation` precheck fix + full-suite verification

**Files:**
- Modify: `src/eigsep_observing/scripts/no_switch_observation.py` (precheck line 100-103)
- Test: `tests/test_motor_scripts.py`

**Interfaces:**
- Consumes: `vna_enabled` (Task 2). The session itself is opened inside `run_calibration_sequence` (Task 5), so this script only needs the precheck fixed.

- [ ] **Step 1: Fix the precheck**

In `src/eigsep_observing/scripts/no_switch_observation.py`, change (lines 100-103):

```python
            if client.vna is None:
                raise RuntimeError(
                    "VNA not initialized; check vna config block."
                )
```

to:

```python
            if not client.vna_enabled:
                raise RuntimeError(
                    "VNA disabled (use_vna=false); check vna config block."
                )
```

- [ ] **Step 2: Run the script tests**

Run: `uv run pytest tests/test_motor_scripts.py -q -k no_switch`
Expected: PASS (update any assertion expecting the old `"VNA not initialized"` message to `"VNA disabled"`, same as Task 7 Step 4).

- [ ] **Step 3: Full suite**

Run: `uv run pytest -n auto -q`
Expected: PASS. Investigate any residual `VNA not initialized` failure — it is a `use_vna=True` test that still calls `measure_s11` outside a session; wrap it in `with client.vna_session():` (Task 3 pattern).

- [ ] **Step 4: Full lint**

Run: `uvx ruff check . && uvx ruff format --check .`
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add src/eigsep_observing/scripts/no_switch_observation.py tests/test_motor_scripts.py
git commit -m "feat(vna): no_switch_observation precheck uses vna_enabled"
```

---

## Optional Task 9: `cmt_vna.VNA.close()` (separate repo — cosmetic)

Only if the team wants a named teardown instead of reaching into `vna.s.close()`. In the `CMT-VNA` repo, add:

```python
    def close(self):
        """Close the underlying pyvisa socket resource."""
        if getattr(self, "s", None) is not None:
            self.s.close()
            self.s = None
```

Then in `eigsep_observing.client.vna_close` / `vna.build_vna_subsystem.cleanup`, prefer `vna.close()` when present. Requires bumping `[packages.eigsep-vna]` / `[services.cmtvna].tag` in the eigsep-field manifest. **Skip unless explicitly wanted** — `vna.s.close()` already works for real and `DummyVNA`.

---

## Self-Review

- **Spec coverage:** lazy VNA (Task 2) ✔; session context manager + explicit open/close pair (Task 2) ✔; refcount (Task 2) ✔; readiness probe 30s / ~5.5s (Task 1) ✔; service control with sudo fallback (Task 1) ✔; outside-session guard message (Task 2 Step 5) ✔; vna_loop per-iteration (Task 4) ✔; run_calibration_sequence (Task 5) ✔; vna_position_sweep one-session burst (Task 7) ✔; vna_manual whole-REPL window (Task 6) ✔; dummy path skips systemctl (Task 3) ✔; session ⊃ switch_section ordering (Tasks 4/7) ✔; failed-open stops service (Task 2 test + code) ✔. The spec's `cmt_vna.close()` is Optional Task 9. The eigsep-field slice (activation value, target, sudoers) is the companion plan.
- **Placeholder scan:** none — every step has complete code or an exact command with expected output. Task 3/7/8 "run then fix residual" steps are TDD observation steps with the exact wrap pattern given, not placeholders.
- **Type consistency:** `vna_open`/`vna_close`/`vna_session`/`vna_enabled`/`_manage_vna_service`/`_vna_depth`/`_vna_enabled` used identically across Tasks 2-8; `vna_service.start/stop/wait_ready` signatures match Task 1 throughout.
