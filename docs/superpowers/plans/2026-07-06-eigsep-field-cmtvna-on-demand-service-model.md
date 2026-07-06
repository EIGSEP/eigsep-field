# eigsep-field — cmtvna On-Demand Service Model Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Repo:** `/home/eigsep/eigsep/eigsep-field`. Start from a clean branch off `main`
> (the spec + plans already live on `feat/cmtvna-on-demand`; continue there or
> branch from it).
>
> **Companion spec:** `docs/superpowers/specs/2026-07-06-cmtvna-on-demand-service-design.md`
> **Companion plan (land together, FIRST):** `2026-07-06-eigsep_observing-vna-on-demand-session.md`
>
> **Sequencing:** the eigsep_observing plan must ship first. An on-demand image with
> an old observe build would never start `cmtvna.service`. Merge this repo's change
> only once the observe side (which actually starts/stops the service) is ready.

**Goal:** Make `cmtvna.service` installed-but-not-auto-started on the panda (a new `on-demand` activation), remove it from the boot targets, and grant the `eigsep` user passwordless `systemctl start/stop` of exactly that unit — so the observe-side code can bring it up only around an S11 window.

**Architecture:** Introduce a third `[services.*].activation` value, `"on-demand"`, that every manifest consumer handles explicitly: `services_for_role` treats it like a role service for *membership* (so `eigsep-field services start/stop cmtvna` works and doctor sees it) but the enable paths (`enable-always`, `_apply-role`) skip it, and doctor reports a stopped on-demand unit as healthy rather than a failure. Flip `[services.cmtvna]` to it, drop `cmtvna.service` from `eigsep-panda.target`, and add two sudoers lines mirroring the existing picomanager start/stop rules.

**Tech Stack:** Python (stdlib + `tomllib` via `load_manifest`), pytest with `monkeypatch`, pi-gen image staging shell (`00-run.sh`), sudoers.

## Global Constraints

- Ruff, line length **79**; matches sibling repos.
- Never hand-edit `pyproject.toml` `[project]` deps/version — but this plan touches none of that.
- `manifest.toml` is the source of truth for `[services.*]`; the drift checker (`scripts/check_services_drift.py`) compares only `[Unit] After/Wants/Requires/Before` + `[Service] User/Group/Restart/Type` + ExecStart argv0 for `kind == "sibling"` units — it ignores `[Install] WantedBy` and does not inspect role targets, so the changes here stay drift-green.
- The image is uniform across Pis; per-Pi behavior comes from `/boot/firmware/eigsep-role.conf`.

---

## File Structure

- **Modify** `src/eigsep_field/_services.py` — `services_for_role` (lines 56-74): include `on-demand` services whose `role` matches.
- **Modify** `src/eigsep_field/cli.py` — `_check_services` (315-339): report on-demand as healthy-when-present; `_cmd_services` list scope label (434-439): show `on-demand`.
- **Modify** `manifest.toml` — `[services.cmtvna].activation` → `"on-demand"`; update the `[services.*]` header comment.
- **Modify** `image/pi-gen-config/stage-eigsep/00-eigsep-install/files/systemd/eigsep-panda.target` — drop `cmtvna.service` from `Wants=`.
- **Modify** `image/pi-gen-config/stage-eigsep/00-eigsep-install/files/sudoers.d/eigsep-field` — add cmtvna start/stop NOPASSWD lines.
- **Modify** `CLAUDE.md` — document the `on-demand` activation value.
- **Modify** `docs/operator/new-pi.md` (or the panda runbook) — note cmtvna is on-demand.
- **Test** `tests/test_on_demand_services.py` (new) — activation semantics.

---

## Task 1: `on-demand` activation semantics in the CLI

**Files:**
- Modify: `src/eigsep_field/_services.py:56-74`
- Modify: `src/eigsep_field/cli.py:315-339` and `:434-439`
- Test: `tests/test_on_demand_services.py` (new)

**Interfaces:**
- Produces: `services_for_role` includes `activation == "on-demand"` entries whose `role` matches (like `role` services) — this puts them in the doctor `expected` set and the `services start/stop` allow-list, WITHOUT the enable paths touching them (those gate on `activation != "role"`/`!= "always"` and already skip on-demand). `_check_services` reports an on-demand unit as `ok` ("on-demand (operator/observe-managed)") regardless of active/enabled state.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_on_demand_services.py`:

```python
from eigsep_field import cli
from eigsep_field._services import RoleConfig, services_for_role


def _manifest():
    return {
        "packages": {},
        "services": {
            "redis": {"unit": "redis-server.service", "activation": "always"},
            "picomanager": {
                "unit": "picomanager.service",
                "activation": "role",
                "role": "panda",
            },
            "cmtvna": {
                "unit": "cmtvna.service",
                "activation": "on-demand",
                "role": "panda",
            },
        },
    }


def test_services_for_role_includes_on_demand_for_matching_role():
    services = _manifest()["services"]
    names = {n for n, _ in services_for_role(services, "panda")}
    assert "cmtvna" in names  # controllable + visible on the panda
    assert "picomanager" in names
    assert "redis" in names


def test_services_for_role_excludes_on_demand_for_other_role():
    services = _manifest()["services"]
    names = {n for n, _ in services_for_role(services, "backend")}
    assert "cmtvna" not in names
    assert "picomanager" not in names
    assert "redis" in names  # always-services are on every role


def test_check_services_reports_on_demand_present_not_failed(monkeypatch):
    # unit_health must NOT decide on-demand health (stopped is normal).
    def fail_if_called(_unit):
        raise AssertionError("unit_health called for an on-demand unit")

    monkeypatch.setattr(cli, "unit_health", fail_if_called)
    ok, problems = cli._check_services(_manifest(), RoleConfig("panda"))
    assert problems == []
    assert any("cmtvna.service" in line and "on-demand" in line for line in ok)


def test_check_services_skips_on_demand_on_other_role(monkeypatch):
    monkeypatch.setattr(cli, "unit_health", lambda _u: (True, "active"))
    ok, problems = cli._check_services(_manifest(), RoleConfig("backend"))
    assert problems == []
    assert any("cmtvna.service" in line and "skipped" in line for line in ok)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_on_demand_services.py -q`
Expected: FAIL — `test_services_for_role_includes_on_demand_for_matching_role` fails (`cmtvna` excluded today) and `test_check_services_reports_on_demand_present_not_failed` fails (`unit_health` is called → AssertionError).

- [ ] **Step 3: Update `services_for_role`**

In `src/eigsep_field/_services.py`, change the loop (lines 65-73):

```python
    for name, entry in services.items():
        activation = entry.get("activation")
        if activation == "always":
            out.append((name, entry))
            continue
        if activation != "role":
            continue
        if entry.get("role") == role:
            out.append((name, entry))
    return out
```

to:

```python
    for name, entry in services.items():
        activation = entry.get("activation")
        if activation == "always":
            out.append((name, entry))
            continue
        # "role" (enabled on first boot) and "on-demand" (installed but
        # started only by the owning process) are both role-scoped for
        # membership: they belong to this Pi and are controllable here.
        # The enable paths (enable-always, _apply-role) gate separately on
        # activation and skip on-demand, so it is never auto-started.
        if activation not in ("role", "on-demand"):
            continue
        if entry.get("role") == role:
            out.append((name, entry))
    return out
```

- [ ] **Step 4: Update `_check_services`**

In `src/eigsep_field/cli.py`, replace the loop body of `_check_services` (lines 323-338):

```python
    for name, entry in services.items():
        unit = entry["unit"]
        activation = entry.get("activation")
        tag = (
            "always"
            if activation == "always"
            else f"role: {entry.get('role', '?')}"
        )
        if name not in expected:
            ok.append(f"{unit} skipped (not this role — {tag})")
            continue
        healthy, state = unit_health(unit)
        if healthy:
            ok.append(f"{unit} {state} ({tag})")
        else:
            problems.append(f"{unit} {state} ({tag})")
    return ok, problems
```

with:

```python
    for name, entry in services.items():
        unit = entry["unit"]
        activation = entry.get("activation")
        if activation == "always":
            tag = "always"
        elif activation == "on-demand":
            tag = "on-demand"
        else:
            tag = f"role: {entry.get('role', '?')}"
        if name not in expected:
            ok.append(f"{unit} skipped (not this role — {tag})")
            continue
        if activation == "on-demand":
            # Started only by the owning process (panda_observe /
            # vna_manual) around a measurement window; a stopped unit is
            # the normal, healthy state, so do not health-gate it.
            ok.append(f"{unit} on-demand (operator/observe-managed)")
            continue
        healthy, state = unit_health(unit)
        if healthy:
            ok.append(f"{unit} {state} ({tag})")
        else:
            problems.append(f"{unit} {state} ({tag})")
    return ok, problems
```

- [ ] **Step 5: Update the `services list` scope label**

In `src/eigsep_field/cli.py`, in `_cmd_services` (lines 434-439), replace:

```python
            activation = entry.get("activation", "?")
            scope = (
                "always"
                if activation == "always"
                else f"role: {entry.get('role', '?')}"
            )
```

with:

```python
            activation = entry.get("activation", "?")
            if activation == "always":
                scope = "always"
            elif activation == "on-demand":
                scope = "on-demand"
            else:
                scope = f"role: {entry.get('role', '?')}"
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_on_demand_services.py -q`
Expected: PASS (4 passed).

- [ ] **Step 7: Lint**

Run: `python -m ruff check src/eigsep_field/_services.py src/eigsep_field/cli.py tests/test_on_demand_services.py && python -m ruff format --check src/eigsep_field/_services.py src/eigsep_field/cli.py tests/test_on_demand_services.py`
Expected: no errors. (Use `uvx ruff` if `python -m ruff` is unavailable.)

- [ ] **Step 8: Commit**

```bash
git add src/eigsep_field/_services.py src/eigsep_field/cli.py tests/test_on_demand_services.py
git commit -m "feat(services): add on-demand activation semantics to the CLI"
```

---

## Task 2: Flip cmtvna to on-demand + drop it from the boot target

**Files:**
- Modify: `manifest.toml` (`[services.cmtvna].activation`; the `[services.*]` header comment)
- Modify: `image/pi-gen-config/stage-eigsep/00-eigsep-install/files/systemd/eigsep-panda.target`
- Test: `tests/test_on_demand_services.py` (append enable-path guard tests)

**Interfaces:**
- Consumes: `services_for_role` on-demand semantics (Task 1).
- Produces: cmtvna is neither enabled at build (`enable-always`) nor at first boot (`_apply-role`), and the panda target no longer pulls it.

- [ ] **Step 1: Write the failing enable-path guard tests**

Append to `tests/test_on_demand_services.py`:

```python
def _capture_systemctl(monkeypatch, module):
    seen = []

    def fake(*args):
        seen.append(tuple(args))
        return 0, ""

    monkeypatch.setattr(module, "systemctl", fake)
    return seen


def test_enable_always_skips_on_demand(monkeypatch):
    from eigsep_field import _image_install

    monkeypatch.setattr(_image_install, "load_manifest", _manifest)
    seen = _capture_systemctl(monkeypatch, _image_install)
    assert _image_install._cmd_enable_always(None) == 0
    # Only the always-service (redis) is enabled at build time.
    assert seen == [("enable", "redis-server.service")]
    assert not any("cmtvna.service" in c for c in seen)


def test_apply_role_does_not_enable_on_demand(monkeypatch, tmp_path):
    from eigsep_field import cli
    from eigsep_field._services import RoleConfig

    monkeypatch.setattr(cli, "load_manifest", _manifest)
    # Neutralize the non-service side effects of apply-role.
    monkeypatch.setattr(cli, "_apply_role_static_ip", lambda _c: 0)
    monkeypatch.setattr(cli, "_apply_role_hostname", lambda _c: 0)
    monkeypatch.setattr(cli, "_apply_chrony_snippet", lambda _c: 0)
    monkeypatch.setattr(cli, "_apply_redis_snippet", lambda _c: 0)
    monkeypatch.setattr(cli, "_write_role_file", lambda _c: None)
    monkeypatch.setattr(cli, "parse_role_file", lambda _p: RoleConfig("panda"))
    seen = _capture_systemctl(monkeypatch, cli)

    role_conf = tmp_path / "eigsep-role.conf"
    role_conf.write_text("role = panda\n")

    class Args:
        role_conf = str(role_conf)

    assert cli._cmd_apply_role(Args()) == 0
    # picomanager (role) is enabled; cmtvna (on-demand) is NOT.
    assert ("enable", "--now", "picomanager.service") in seen
    assert not any("cmtvna.service" in c for c in seen)
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_on_demand_services.py -q -k "enable_always or apply_role"`
Expected: FAIL — until `_manifest()` is used as the manifest, the real manifest is loaded; more importantly, before flipping cmtvna these tests document the target behavior. If they already pass against `_manifest()` (they should, since Task 1 made cmtvna a member but the enable loops gate on `activation`), that is fine — they lock in the guard. Confirm they pass *with* the code as-is; if `apply_role` enables cmtvna, the guard is missing.

  Note: `_cmd_apply_role`'s enable loop already reads `if entry.get("activation") != "role": continue`, so on-demand is skipped without code change. These tests are regression guards. If they pass immediately, proceed; they must never regress.

- [ ] **Step 3: Flip the manifest**

In `manifest.toml`, change `[services.cmtvna]`:

```toml
activation  = "role"
```

to:

```toml
activation  = "on-demand"
```

(Keep `role = "panda"` — it scopes membership to the panda. Keep `kind`, `unit`, `source`, `tag`, `source_path` unchanged.)

Update the `[services.*]` header comment (just above `[services.redis]`) to enumerate the third value — change the sentence describing `always`/`role` to add:

```
# activation="on-demand" services are installed but never enabled by the
# image or first-boot; the owning process (e.g. panda_observe starting
# cmtvna.service around an S11 sweep) starts/stops them. They are still
# role-scoped for `eigsep-field services` control and doctor visibility.
```

- [ ] **Step 4: Drop cmtvna from the panda target**

In `image/pi-gen-config/stage-eigsep/00-eigsep-install/files/systemd/eigsep-panda.target`, change line 3:

```
Wants=redis-server.service picomanager.service cmtvna.service
```

to:

```
Wants=redis-server.service picomanager.service
```

(Leave `cmtvna.service`'s own `[Install] WantedBy=eigsep-panda.target` / `PartOf=` untouched — inert while the unit is never enabled, and ignored by the drift checker.)

- [ ] **Step 5: Run the guard tests + drift/consistency + full suite**

Run:
```
python -m pytest tests/test_on_demand_services.py tests/test_services_drift.py tests/test_cli_services_lifecycle.py -q
```
Expected: PASS. `test_files_systemd_and_manifest_agree` still passes (the `cmtvna.service` unit file and manifest entry both still exist; only the target `Wants=` and the activation value changed). If any test asserts `cmtvna.service` appears in `eigsep-panda.target`'s `Wants=`, update it to expect the unit removed.

- [ ] **Step 6: Commit**

```bash
git add manifest.toml image/pi-gen-config/stage-eigsep/00-eigsep-install/files/systemd/eigsep-panda.target tests/test_on_demand_services.py
git commit -m "feat(services): make cmtvna on-demand; drop it from eigsep-panda.target"
```

---

## Task 3: Grant the eigsep user passwordless start/stop of cmtvna

**Files:**
- Modify: `image/pi-gen-config/stage-eigsep/00-eigsep-install/files/sudoers.d/eigsep-field`
- Test: `tests/test_on_demand_services.py` (append)

**Interfaces:**
- Produces: two `NOPASSWD` sudoers lines letting `eigsep` run `systemctl start|stop --no-ask-password cmtvna.service` — the fallback the observe-side `vna_service` module uses.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_on_demand_services.py`:

```python
from pathlib import Path

SUDOERS = (
    Path(__file__).resolve().parents[1]
    / "image/pi-gen-config/stage-eigsep/00-eigsep-install/files"
    / "sudoers.d/eigsep-field"
)


def test_sudoers_allows_cmtvna_start_stop():
    text = SUDOERS.read_text()
    assert (
        "NOPASSWD: /usr/bin/systemctl start --no-ask-password "
        "cmtvna.service" in text
    )
    assert (
        "NOPASSWD: /usr/bin/systemctl stop --no-ask-password "
        "cmtvna.service" in text
    )
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_on_demand_services.py -q -k sudoers`
Expected: FAIL — the cmtvna lines are not present yet.

- [ ] **Step 3: Add the sudoers lines**

Append to `image/pi-gen-config/stage-eigsep/00-eigsep-install/files/sudoers.d/eigsep-field` (after the existing picomanager lines):

```
# cmtvna.service is on-demand (the CMT R60 binary busy-loops the CPU):
# panda_observe / vna_manual start it around an S11 window and stop it
# after. The eigsep_observing vna_service module tries plain systemctl
# then `sudo -n`; these rules make the fallback passwordless for exactly
# this unit and nothing else.
eigsep ALL=(root) NOPASSWD: /usr/bin/systemctl stop --no-ask-password cmtvna.service
eigsep ALL=(root) NOPASSWD: /usr/bin/systemctl start --no-ask-password cmtvna.service
```

- [ ] **Step 4: Run the test**

Run: `python -m pytest tests/test_on_demand_services.py -q -k sudoers`
Expected: PASS.

- [ ] **Step 5: Sanity-check syntax (if `visudo` is available)**

Run: `visudo -cf image/pi-gen-config/stage-eigsep/00-eigsep-install/files/sudoers.d/eigsep-field`
Expected: `... parsed OK`. (Skip if `visudo` is not installed on the dev box; the image build validates on-device.)

- [ ] **Step 6: Commit**

```bash
git add image/pi-gen-config/stage-eigsep/00-eigsep-install/files/sudoers.d/eigsep-field tests/test_on_demand_services.py
git commit -m "feat(image): allow eigsep user to start/stop cmtvna.service passwordless"
```

---

## Task 4: Documentation

**Files:**
- Modify: `CLAUDE.md` (lines 231-235, the activation enumeration)
- Modify: `docs/operator/new-pi.md` (or the panda bring-up runbook)

**Interfaces:** none (docs only).

- [ ] **Step 1: Update CLAUDE.md**

In `CLAUDE.md`, under "## When adding a systemd service to the image", change the `activation` bullet (lines 231-233):

```
   - `activation` — `"always"` (enabled on every Pi at build time) or
     `"role"` (enabled on first boot when `/boot/firmware/eigsep-role.conf`
     matches).
```

to:

```
   - `activation` — `"always"` (enabled on every Pi at build time),
     `"role"` (enabled on first boot when `/boot/firmware/eigsep-role.conf`
     matches), or `"on-demand"` (installed but never enabled by the image
     or first boot; the owning process starts/stops it around use — e.g.
     `cmtvna.service`, which the observe-side `vna_service` module brings
     up only around an S11 sweep because the CMT binary busy-loops the
     CPU). On-demand services still take `role` (for `eigsep-field
     services` control + doctor visibility) but must NOT be added to the
     role `.target`'s `Wants=`, and need a sudoers line if a non-root
     process starts them.
```

- [ ] **Step 2: Update the operator runbook**

In `docs/operator/new-pi.md` (or the panda-specific runbook), add a short note under the panda section:

```markdown
### cmtvna.service is on-demand

`cmtvna.service` (the CMT R60 VNA driver) is **not** started at boot —
the CMT binary busy-loops at ~300% CPU whenever it runs, so it is kept
stopped and brought up only around an S11 measurement by the observe-side
code (`panda_observe` / `vna_manual`). `eigsep-field doctor` reports it as
`on-demand (operator/observe-managed)`, which is healthy even when the
unit is inactive. To exercise it by hand: `eigsep-field services start
cmtvna` then `... stop cmtvna` (both passwordless for the `eigsep` user).
```

(If `docs/operator/new-pi.md` does not exist, add this section to whatever panda bring-up doc `docs/operator/` provides; grep `docs/operator` for "panda".)

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md docs/operator/
git commit -m "docs: document on-demand activation and cmtvna service model"
```

---

## Self-Review

- **Spec coverage:** new `on-demand` activation value (Task 1/2) ✔; `_cmd_apply_role` + `enable-always` skip (Task 1 semantics + Task 2 guard tests) ✔; drop from `eigsep-panda.target` `Wants=` (Task 2) ✔; unit file `[Service]` unchanged → drift green (Task 2 Step 5) ✔; doctor reports on-demand as healthy-when-present (Task 1) ✔; sudoers instead of polkit — follows the existing picomanager precedent, a deliberate deviation from the spec's original polkit choice, noted for the reviewer (Task 3) ✔; docs (Task 4) ✔.
- **Placeholder scan:** none — every step has complete code/diff or an exact command with expected output.
- **Type consistency:** `activation == "on-demand"` handled identically in `services_for_role`, `_check_services`, and `_cmd_services`; `_manifest()` test helper shape matches the real `[services.*]` schema (`unit`, `activation`, `role`).
- **Deviation flagged:** the spec specifies a polkit rule; this plan uses a sudoers drop-in instead because the repo already grants `eigsep` passwordless `systemctl start/stop picomanager.service` there — following the established pattern. Confirm with the spec owner (already surfaced to the user); if polkit is preferred, replace Task 3 with a `files/polkit/49-eigsep-cmtvna.rules` drop + a staging block in `00-run.sh`.
