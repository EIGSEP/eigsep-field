# Field-KB Phase 1 (MVP) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the minimum viable offline field-KB corpus + AnythingLLM setup so an operator can ask grounded troubleshooting questions on a laptop, and prove the retrieval loop with a model bake-off.

**Architecture:** Curated operator markdown lives in `docs/field-kb/` in this repo. A Python script `scripts/build-field-kb.py` assembles that KB plus the interface ICDs, the operator runbooks, and the source/doc trees of the blessed field-stack siblings (enumerated from `manifest.toml`, mirroring the image build's `_clone_targets`) into a single importable corpus folder, stamped with a `CORPUS-MANIFEST.md`. The operator installs Ollama + AnythingLLM on each Linux laptop (per `setup.md`), imports the corpus, pastes the workspace prompt, and runs the bake-off question set to pick the local model.

**Tech Stack:** Python 3.13 (stdlib only: `argparse`, `shutil`, `subprocess`, `fnmatch`, `pathlib`, `datetime`, `tomllib`), pytest (existing harness, `testpaths=["tests"]`, `pythonpath=["src"]`), AnythingLLM Desktop + Ollama (operator-side, Linux), Markdown.

**Scope:** Phase 1 only (per the spec's phasing). Phase 2 (per-repo code maps, hand-curated hardware notes, FAQ, remaining runbooks) and Phase 3 (`field-kb.yml` CI + `refresh-field-kb.sh` + release-checklist prompts) get their own plans.

**Spec:** `docs/superpowers/specs/2026-06-15-field-kb-anythingllm-design.md`

**Branch:** Continue on `docs/field-kb-anythingllm-spec` (where the spec is committed) or cut `feat/field-kb-phase1` from it. Do not work on `main`.

---

## File Structure

Created in this phase:

- `docs/field-kb/README.md` — map-of-content hub (the human "lookup index").
- `docs/field-kb/topology.md` — role map / what-runs-where / IPs (operator-facing distillation of `CLAUDE.md`).
- `docs/field-kb/glossary.md` — acronym + term anchors for the RAG embedder.
- `docs/field-kb/runbooks/no-correlator-data.md` — backend/SNAP troubleshooting.
- `docs/field-kb/runbooks/dhcp-not-serving.md` — backend DHCP troubleshooting.
- `docs/field-kb/runbooks/pico-wont-flash.md` — panda/Pico troubleshooting.
- `docs/field-kb/runbooks/vna-not-found.md` — panda/CMT-VNA troubleshooting.
- `docs/field-kb/anythingllm/setup.md` — Linux install guide (Ollama + AnythingLLM + model pulls + import).
- `docs/field-kb/anythingllm/workspace-prompt.md` — operator-troubleshooting system prompt.
- `docs/field-kb/anythingllm/bakeoff.md` — fixed question set + scoring table to pick the model.
- `docs/field-kb/anythingllm/corpus.ignore` — exclude globs for corpus assembly.
- `scripts/build-field-kb.py` — corpus assembly script.
- `tests/test_field_kb.py` — KB structure/invariant validation.
- `tests/test_build_field_kb.py` — unit/integration tests for the build script.

Reused (not modified): `manifest.toml`, `src/eigsep_field/__init__.py` (`load_manifest`), `docs/interface/**`, `docs/operator/**`.

---

## Task 1: Corpus ignore list + KB structure test scaffold

**Files:**
- Create: `docs/field-kb/anythingllm/corpus.ignore`
- Create: `tests/test_field_kb.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_field_kb.py`:

```python
"""Structure + invariant checks for the curated field-KB (docs/field-kb).

These guard the operator knowledge base: required files exist, the
glossary defines the load-bearing acronyms, and every runbook carries
the diagnostic section headings the operator agent relies on. Content
quality is the deliverable here, so the test encodes the contract.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
KB = REPO_ROOT / "docs" / "field-kb"


def test_corpus_ignore_excludes_blobs_keeps_docs():
    patterns = (KB / "anythingllm" / "corpus.ignore").read_text()
    # Big binaries must be excluded from a text RAG index.
    for pat in (".git/", ".venv/", "*.img", "*.npz", "__pycache__/"):
        assert pat in patterns, f"missing ignore pattern: {pat}"
    # But hardware PDFs/docx are shipped on purpose.
    assert "*.pdf" not in patterns
    assert "*.docx" not in patterns
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_field_kb.py -v`
Expected: FAIL — `FileNotFoundError` (corpus.ignore does not exist).

- [ ] **Step 3: Create the ignore list**

Create `docs/field-kb/anythingllm/corpus.ignore`:

```gitignore
# corpus.ignore — paths excluded when build-field-kb.py assembles the
# AnythingLLM corpus. One glob per line; '#' comments and blank lines
# ignored. Matched against the path relative to each copied root and
# against each path component (so "dir/" excludes that directory
# anywhere in the tree).

# version control, virtualenvs, caches
.git/
.venv/
venv/
__pycache__/
*.pyc
.pytest_cache/
.ruff_cache/
.mypy_cache/
node_modules/

# build artifacts
build/
dist/
*.egg-info/

# vendored SDKs / submodules that bloat the index without operator value
pico-sdk/
picotool/

# large binaries / blobs — useless to a text RAG index
*.img
*.img.xz
*.tar
*.tar.gz
*.tar.xz
*.zip
*.npz
*.npy
*.bin
*.uf2
*.so
*.o
*.a
*.elf

# NOTE: *.pdf and *.docx are deliberately NOT excluded — the CMT vendor
# manuals and the correlator notes are shipped as corpus content.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_field_kb.py -v`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add docs/field-kb/anythingllm/corpus.ignore tests/test_field_kb.py
git commit -m "feat(field-kb): corpus.ignore + KB structure test scaffold"
```

---

## Task 2: README map-of-content hub

**Files:**
- Create: `docs/field-kb/README.md`
- Modify: `tests/test_field_kb.py`

- [ ] **Step 1: Add the failing assertion**

Append to `tests/test_field_kb.py`:

```python
def test_readme_links_to_core_sections():
    readme = (KB / "README.md").read_text()
    for target in ("topology.md", "glossary.md", "runbooks/", "anythingllm/setup.md"):
        assert target in readme, f"README missing pointer to {target}"
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_field_kb.py::test_readme_links_to_core_sections -v`
Expected: FAIL — `FileNotFoundError` (README.md missing).

- [ ] **Step 3: Create the README hub**

Create `docs/field-kb/README.md`:

```markdown
# EIGSEP field knowledge base

This is the operator knowledge base for the EIGSEP field stack — the
content fed to the offline AnythingLLM troubleshooting agent on the
field laptop. It is written for an operator standing at the
deployment, not for developers.

## Start here

- **[topology.md](topology.md)** — which Pi runs what, how things are
  wired, the LAN addresses. Read this first when something is "not
  responding".
- **[glossary.md](glossary.md)** — what every acronym means
  (SNAP, RFSoC, CMT-VNA, panda/backend, …).

## Runbooks (symptom → fix)

See [runbooks/](runbooks/):

- [No correlator data](runbooks/no-correlator-data.md) — backend Pi / SNAP.
- [DHCP not serving](runbooks/dhcp-not-serving.md) — backend Pi / LAN.
- [Pico won't flash](runbooks/pico-wont-flash.md) — panda Pi / Pico.
- [VNA not found](runbooks/vna-not-found.md) — panda Pi / CMT-VNA.

## Running the agent

- [anythingllm/setup.md](anythingllm/setup.md) — install Ollama +
  AnythingLLM on the laptop and import this corpus.
- [anythingllm/workspace-prompt.md](anythingllm/workspace-prompt.md) —
  the system prompt to paste into the workspace.
- [anythingllm/bakeoff.md](anythingllm/bakeoff.md) — the question set
  for choosing the local model.

## How this corpus is built

`scripts/build-field-kb.py` assembles this KB plus the interface ICDs
(`docs/interface/`), the operator runbooks (`docs/operator/`), and the
source trees of the blessed field-stack siblings into a single folder
to import into AnythingLLM. The corpus is pinned to the manifest
release; see the generated `CORPUS-MANIFEST.md` inside any built corpus
for the exact version and per-repo commits.
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_field_kb.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add docs/field-kb/README.md tests/test_field_kb.py
git commit -m "feat(field-kb): map-of-content README hub"
```

---

## Task 3: Topology / role map

**Files:**
- Create: `docs/field-kb/topology.md`
- Modify: `tests/test_field_kb.py`

- [ ] **Step 1: Add the failing assertion**

Append to `tests/test_field_kb.py`:

```python
def test_topology_covers_roles_and_addresses():
    text = (KB / "topology.md").read_text()
    for token in ("panda", "backend", "SNAP", "RFSoC", "10.10.10.10", "DHCP"):
        assert token in text, f"topology.md missing {token}"
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_field_kb.py::test_topology_covers_roles_and_addresses -v`
Expected: FAIL — `FileNotFoundError`.

- [ ] **Step 3: Create topology.md**

Create `docs/field-kb/topology.md` (content distilled from `CLAUDE.md` "Topology / what runs where"):

```markdown
# Topology — what runs where

The field image is uniform across Pis. A Pi's job is set by its **role**
in `/boot/firmware/eigsep-role.conf` (`role = panda` or
`role = backend`), applied on first boot by `eigsep-first-boot.service`.
Role is decoupled from the hardware model.

## panda Pi

- **Runs:** `picomanager.service`, `cmtvna.service`.
- **Wired to:** the Raspberry Pi Pico(s) over USB, and the CMT VNA.
- **Owns:** flashing the Pico(s) — `eigsep-field patch pico-firmware`
  builds and flashes the UF2 from this Pi.
- The panda-side observing entry point, `panda_observe`, is launched by
  the operator (not a systemd service) and drives the actuators via the
  Pico firmware (`picohost`).

## backend Pi

- **Runs:** `eigsep-observe.service`, `eigsep-observe-writer.service`,
  `redis-server`, and the LAN's `isc-dhcp-server`.
- **Wired to:** the SNAP board; it reads correlator data from the SNAP
  via `casperfpga` (the SNAP driver — required on backend).
- **Is the LAN's DHCP and NTP server by definition.** The backend role
  pins `eth0` to **`10.10.10.10/24`**, enables `isc-dhcp-server`, and
  serves chrony time.

## RFSoC

- A **separate standalone system — not a Pi**, does not run the eigsep
  image. The backend Pi holds the RFSoC bitstream `.npz` at
  `/opt/eigsep/firmware/rfsoc/` and pushes it to the RFSoC over the
  network.

## The LAN

- Subnet `10.10.10.0/24`. Backend Pi at `10.10.10.10` serves DHCP/NTP to
  the other nodes. The field image ships with WiFi disabled.
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_field_kb.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add docs/field-kb/topology.md tests/test_field_kb.py
git commit -m "feat(field-kb): topology / role map"
```

---

## Task 4: Glossary

**Files:**
- Create: `docs/field-kb/glossary.md`
- Modify: `tests/test_field_kb.py`

- [ ] **Step 1: Add the failing assertion**

Append to `tests/test_field_kb.py`:

```python
def test_glossary_defines_core_terms():
    text = (KB / "glossary.md").read_text()
    required = [
        "SNAP", "RFSoC", "CMT-VNA", "Pico", "picohost", "casperfpga",
        "panda", "backend", "correlator", "chrony", "DHCP", "Valon",
    ]
    for term in required:
        # each term must appear as a definition heading "## <term>"
        assert f"## {term}" in text or f"## {term} " in text, (
            f"glossary missing definition heading for {term}"
        )
    # an embedder-friendly glossary should be reasonably complete
    assert text.count("## ") >= 12
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_field_kb.py::test_glossary_defines_core_terms -v`
Expected: FAIL — `FileNotFoundError`.

- [ ] **Step 3: Create glossary.md**

Create `docs/field-kb/glossary.md`. Each term is a `## <term>` heading with a one-to-three sentence definition (self-contained so a chunk retrieves cleanly):

```markdown
# Glossary

One anchored definition per term. Acronyms are spelled out so the agent
can answer questions that use either form.

## SNAP
Smart Network ADC Processor — the CASPER FPGA board on the
**backend** Pi that digitizes and correlates the antenna signals. The
backend reads correlator data off it via `casperfpga`.

## RFSoC
Radio Frequency System-on-Chip — a separate standalone signal-generation
system (not a Pi, does not run the eigsep image). The backend Pi pushes
it a bitstream `.npz` over the network.

## CMT-VNA
The Copper Mountain Technologies Vector Network Analyzer attached to the
**panda** Pi, driven by `cmtvna.service`. Used for calibration
measurements. The vendor binary is installed under `/opt/eigsep/cmt-vna`.

## Pico
The Raspberry Pi Pico microcontroller(s) on the **panda** Pi, connected
over USB, running the EIGSEP C firmware. Flashed from the panda Pi.

## picohost
The Python package (in the `pico-firmware` repo) that talks to the Pico
over USB from the panda Pi. `picomanager.service` and `panda_observe`
use it.

## picomanager
The systemd service on the panda Pi that supervises communication with
the Pico(s).

## panda
The Pi **role** that runs the Pico host and the CMT VNA
(`picomanager.service`, `cmtvna.service`). Set by `role = panda` in
`/boot/firmware/eigsep-role.conf`.

## backend
The Pi **role** that runs the observing stack, Redis, and the LAN's
DHCP/NTP. Reads the SNAP correlator. Pinned to `eth0 = 10.10.10.10/24`.
Set by `role = backend` in `/boot/firmware/eigsep-role.conf`.

## casperfpga
The Python driver for the SNAP board. Required on the **backend** Pi
(`[hardware.casperfpga] roles = ["backend"]`). Missing it on a real
backend is an image-build bug, not optional.

## correlator
The SNAP-based cross-correlation engine that produces the visibility
data the observing stack records.

## Redis buses
The named message buses (`metadata`, `status`, `heartbeat`, `config`)
that the observing stack uses for inter-process communication via
`redis-server` on the backend Pi. Each bus has one writer and many
readers by construction.

## eigsep-observe
The backend systemd service that runs the observing loop.

## eigsep-observe-writer
The backend systemd service that writes observed data to disk.

## panda_observe
The operator-launched (not systemd) entry point on the panda Pi that
drives the actuators via `picohost` and runs the observing loop.

## chrony
The NTP daemon. The backend Pi serves time to the LAN; field Pis
discipline their clocks against it (plus an RTC on the backend).

## RTC
Real-Time Clock — a coin-cell-backed clock on the backend Pi 5 so it
keeps time across power cycles without a network sync.

## DHCP
Dynamic Host Configuration Protocol. The backend Pi runs
`isc-dhcp-server` and hands out `10.10.10.0/24` addresses to the LAN.

## Valon
The Valon frequency synthesizer, driven by the `pyvalon` package; the
local-oscillator / clock source for the signal chain.

## manifest / blessed tuple
`manifest.toml` in `eigsep-field` — the `==`-pinned set of sibling
package versions for a deployment campaign. The image, wheelhouse, and
this corpus are all built from it.

## eigsep-field
The umbrella repo (this one). Owns the manifest, the image recipe, the
`eigsep-field` CLI (`info`, `doctor`, `services`, `patch`), and this KB.

## doctor
`eigsep-field doctor` — the on-Pi health check that verifies packages,
firmware blobs, services, and role config for the Pi's role.

## bitstream
The FPGA configuration loaded onto the SNAP/RFSoC. The RFSoC bitstream
ships as a `.npz` staged on the backend Pi.

## UF2
The flashable firmware image format for the Pico. The blessed UF2 lives
at `/opt/eigsep/firmware/pico/`.
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_field_kb.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add docs/field-kb/glossary.md tests/test_field_kb.py
git commit -m "feat(field-kb): glossary of stack acronyms and terms"
```

---

## Task 5: The four MVP runbooks

**Files:**
- Create: `docs/field-kb/runbooks/no-correlator-data.md`
- Create: `docs/field-kb/runbooks/dhcp-not-serving.md`
- Create: `docs/field-kb/runbooks/pico-wont-flash.md`
- Create: `docs/field-kb/runbooks/vna-not-found.md`
- Modify: `tests/test_field_kb.py`

- [ ] **Step 1: Add the failing assertion**

Append to `tests/test_field_kb.py`:

```python
def test_runbooks_have_required_sections():
    runbooks = sorted((KB / "runbooks").glob("*.md"))
    assert len(runbooks) >= 4, "expected at least 4 MVP runbooks"
    for rb in runbooks:
        text = rb.read_text()
        for heading in ("## Symptom", "## Diagnosis", "## Fix"):
            assert heading in text, f"{rb.name} missing '{heading}'"
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_field_kb.py::test_runbooks_have_required_sections -v`
Expected: FAIL — runbooks dir empty / does not exist.

- [ ] **Step 3a: Create `runbooks/no-correlator-data.md`**

```markdown
# Runbook: no correlator data

**Where:** backend Pi (SNAP).

## Symptom
The observing stack reports no visibilities, or `eigsep-observe` logs
read errors from the SNAP.

## Likely causes
- `eigsep-observe.service` or `eigsep-observe-writer.service` not running.
- `redis-server` down (the buses are unavailable).
- `casperfpga` missing/broken, or the SNAP not reachable on the LAN.
- The SNAP bitstream not programmed.

## Diagnosis
Run on the backend Pi:

    systemctl status eigsep-observe.service eigsep-observe-writer.service
    journalctl -u eigsep-observe.service -n 100 --no-pager
    systemctl status redis-server.service
    redis-cli ping            # expect: PONG
    ip addr show eth0         # expect inet 10.10.10.10/24
    eigsep-field doctor

`eigsep-field doctor` is role-aware and will flag a missing `casperfpga`
or firmware blob on the backend.

## Fix
- Restart the observing services:
  `sudo systemctl restart eigsep-observe.service eigsep-observe-writer.service`.
- If `redis-cli ping` fails: `sudo systemctl restart redis-server.service`.
- If `doctor` reports `casperfpga` missing: the image is mis-built;
  reinstall hardware wheels from the wheelhouse (see
  `docs/operator/new-pi.md`).
- If the SNAP is unreachable: check the SNAP's power and Ethernet, and
  that it pulled a DHCP lease (see the DHCP runbook).
```

- [ ] **Step 3b: Create `runbooks/dhcp-not-serving.md`**

```markdown
# Runbook: DHCP not serving (LAN nodes get no address)

**Where:** backend Pi (the LAN's DHCP server).

## Symptom
SNAP / panda Pi / other LAN nodes don't get an IP, or can't reach the
backend at `10.10.10.10`.

## Likely causes
- `isc-dhcp-server.service` not running on the backend.
- `eth0` not at `10.10.10.10/24` (role not applied).
- Cabling / switch power.

## Diagnosis
On the backend Pi:

    systemctl status isc-dhcp-server.service
    journalctl -u isc-dhcp-server.service -n 100 --no-pager
    ip addr show eth0                 # expect inet 10.10.10.10/24
    cat /boot/firmware/eigsep-role.conf   # expect role = backend
    cat /var/lib/dhcp/dhcpd.leases | tail

## Fix
- If the role line is wrong: set `role = backend`, then re-apply the
  role. `eigsep-first-boot.service` self-disables after its first run, so
  a `restart` will NOT re-apply it. Re-enable it and reboot:
  `sudo systemctl enable eigsep-first-boot.service` then `sudo reboot`.
  That re-applies the static IP and enables the role services.
- If the service is down: `sudo systemctl restart isc-dhcp-server.service`.
- If `eth0` has no/!wrong address: re-apply the role as above; confirm
  the cable is in the correct port and the switch is powered.
```

- [ ] **Step 3c: Create `runbooks/pico-wont-flash.md`**

```markdown
# Runbook: Pico won't flash

**Where:** panda Pi (the host that flashes the Pico over USB).

## Symptom
`eigsep-field patch pico-firmware` fails, or the Pico is not detected.

## Likely causes
- Pico not in BOOTSEL/USB mass-storage mode, or USB cable is power-only.
- `picomanager.service` holding the serial port.
- Build toolchain or `picotool` issue.

## Diagnosis
On the panda Pi:

    lsusb | grep -i 'Raspberry\|2e8a'   # 2e8a = Raspberry Pi vendor id
    picotool info                        # expect device info
    systemctl status picomanager.service

## Fix
- Stop the host so it releases the device, then flash:
  `sudo systemctl stop picomanager.service`, then
  `eigsep-field patch pico-firmware` (builds + flashes the UF2), then
  `sudo systemctl start picomanager.service`.
- If `picotool` can't see the Pico: replug with a known data USB cable;
  if needed put the Pico in BOOTSEL mode (hold BOOTSEL while plugging).
- To return to the blessed firmware: `eigsep-field revert pico-firmware`
  (deletes the patch drop-in and reflashes the blessed UF2).
```

- [ ] **Step 3d: Create `runbooks/vna-not-found.md`**

```markdown
# Runbook: VNA not found

**Where:** panda Pi (CMT-VNA).

## Symptom
`cmtvna.service` fails to start, or calibration can't reach the VNA.

## Likely causes
- The CMT VNA binary is not installed at `/opt/eigsep/cmt-vna`.
- The VNA is not powered / not enumerated on USB.
- `cmtvna.service` crashed.

## Diagnosis
On the panda Pi:

    eigsep-field doctor               # checks the cmtvna install_path/binary
    ls -l /opt/eigsep/cmt-vna
    lsusb                             # look for the VNA device
    systemctl status cmtvna.service
    journalctl -u cmtvna.service -n 100 --no-pager

## Fix
- If the binary is missing: install it with
  `scripts/install-cmtvna.sh <path-to-archive>` (the operator scp's the
  vendor archive to the Pi first — see `docs/operator/new-pi.md`).
- If the device isn't on USB: check VNA power and the USB cable.
- If the service crashed: `sudo systemctl restart cmtvna.service`.
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_field_kb.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add docs/field-kb/runbooks/ tests/test_field_kb.py
git commit -m "feat(field-kb): four MVP troubleshooting runbooks"
```

---

## Task 6: AnythingLLM setup guide + workspace prompt + bake-off sheet

**Files:**
- Create: `docs/field-kb/anythingllm/setup.md`
- Create: `docs/field-kb/anythingllm/workspace-prompt.md`
- Create: `docs/field-kb/anythingllm/bakeoff.md`
- Modify: `tests/test_field_kb.py`

- [ ] **Step 1: Add the failing assertion**

Append to `tests/test_field_kb.py`:

```python
def test_anythingllm_setup_present():
    anythingllm = KB / "anythingllm"
    for name in ("setup.md", "workspace-prompt.md", "bakeoff.md"):
        assert (anythingllm / name).exists(), f"missing anythingllm/{name}"
    setup = (anythingllm / "setup.md").read_text()
    for token in ("ollama", "qwen2.5:7b-instruct", "nomic-embed-text"):
        assert token in setup, f"setup.md missing {token}"
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_field_kb.py::test_anythingllm_setup_present -v`
Expected: FAIL — files missing.

- [ ] **Step 3a: Create `anythingllm/setup.md`**

```markdown
# Setting up the offline operator agent (Linux laptop)

Do this **online, before the deployment**, on each laptop (the primary
ThinkPad and the spare Ubuntu laptop). Once set up, the agent runs fully
offline in the field.

## 1. Install Ollama (the local model runtime)

    curl -fsSL https://ollama.com/install.sh | sh
    systemctl --user enable --now ollama   # or: ollama serve &

## 2. Pull the models

    ollama pull qwen2.5:7b-instruct   # the LLM (default starting point)
    ollama pull nomic-embed-text      # the embedder

On a 32 GB+ / GPU laptop you may also pull a larger model to compare in
the bake-off, e.g. `ollama pull qwen2.5:14b-instruct`.

## 3. Install AnythingLLM Desktop

Download the Linux AppImage from https://anythingllm.com/desktop, make
it executable, and run it:

    chmod +x AnythingLLM-*.AppImage
    ./AnythingLLM-*.AppImage

## 4. Point AnythingLLM at the local stack

In AnythingLLM settings:
- **LLM Preference:** Ollama → base URL `http://127.0.0.1:11434` → model
  `qwen2.5:7b-instruct`.
- **Embedding Preference:** Ollama → `nomic-embed-text` (or the built-in
  AnythingLLM embedder as a zero-dependency fallback).
- **Vector Database:** the built-in LanceDB (default).

## 5. Build and import the corpus

On a machine with the field-stack siblings checked out next to this repo:

    python scripts/build-field-kb.py --out ./out/field-kb-corpus

Copy `out/field-kb-corpus/` to the laptop, then in AnythingLLM:
- Create a workspace named `eigsep-field`.
- Upload the corpus folder's files (drag the folder into the workspace's
  document upload), then **Save and Embed**.
- Open `CORPUS-MANIFEST.md` from the corpus and note the release version.

## 6. Set the workspace prompt

Paste the contents of `workspace-prompt.md` into the workspace's
**System Prompt** (Workspace Settings → Chat). Fill the corpus release
version into the prompt where indicated.

## 7. Choose the model

Run the question set in `bakeoff.md` against each candidate model and
keep the best. Models hot-swap in AnythingLLM (step 4) without
rebuilding the corpus.
```

- [ ] **Step 3b: Create `anythingllm/workspace-prompt.md`**

```markdown
You are the EIGSEP field operations assistant. You help an operator
troubleshoot the EIGSEP field stack during a deployment, using ONLY the
documents in this workspace (operator runbooks, the topology and
glossary, the interface ICDs, and the stack source code).

Rules:
- Ground every answer in the workspace documents. Cite the source file
  you used.
- If the documents do not contain the answer, say so plainly — do not
  guess. Suggest which runbook or doc might be extended.
- Prefer the runbooks for "X is broken / not working" questions. Give
  the operator concrete commands to run, in order.
- Be concise. The operator may be reading this on a laptop in the field.
- This corpus is pinned to EIGSEP field release <FILL IN FROM
  CORPUS-MANIFEST.md>. If asked about a newer release, note that your
  knowledge is fixed to that version.
```

- [ ] **Step 3c: Create `anythingllm/bakeoff.md`**

```markdown
# Model bake-off

Run this fixed question set against each candidate local model and score
the answers. Goal: pick the default LLM for the field laptops. Models
hot-swap in AnythingLLM without rebuilding the corpus.

## Questions (grounded — answers exist in the corpus)

1. Which Pi runs the DHCP server, and what is its IP address?
2. The SNAP shows no data. What do I check first?
3. How do I flash the Pico, and which Pi do I do it from?
4. What does `casperfpga` do and which role requires it?
5. Where is the RFSoC bitstream stored and how does it get to the RFSoC?
6. What are the Redis buses used for?
7. `cmtvna.service` won't start — walk me through it.
8. What does `eigsep-field doctor` check?
9. What is the difference between the panda and backend roles?
10. How do I revert the Pico to the blessed firmware?

## Scoring (1–5 each: grounded, correct, cites a doc, concise)

| Model | Q1 | Q2 | Q3 | Q4 | Q5 | Q6 | Q7 | Q8 | Q9 | Q10 | Notes |
|-------|----|----|----|----|----|----|----|----|----|-----|-------|
| qwen2.5:7b-instruct  |  |  |  |  |  |  |  |  |  |  | |
| (other candidate)    |  |  |  |  |  |  |  |  |  |  | |

Record the laptop's RAM/GPU and the model's tokens/sec so the choice is
reproducible.
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_field_kb.py -v`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add docs/field-kb/anythingllm/ tests/test_field_kb.py
git commit -m "feat(field-kb): AnythingLLM setup, workspace prompt, bake-off sheet"
```

---

## Task 7: build-field-kb.py — ignore-list parsing + matching

**Files:**
- Create: `scripts/build-field-kb.py`
- Create: `tests/test_build_field_kb.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_build_field_kb.py`:

```python
"""Tests for scripts/build-field-kb.py corpus assembly."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "build-field-kb.py"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "build_field_kb", SCRIPT_PATH
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("build_field_kb", mod)
    spec.loader.exec_module(mod)
    return mod


def test_read_ignore_skips_comments_and_blanks(tmp_path):
    m = _load_module()
    f = tmp_path / "corpus.ignore"
    f.write_text("# comment\n\n.git/\n*.img\n")
    assert m.read_ignore(f) == [".git/", "*.img"]


def test_path_is_ignored_matches_dir_and_glob():
    m = _load_module()
    pats = [".git/", "*.img", "build/"]
    assert m.path_is_ignored("a/.git/config", pats)
    assert m.path_is_ignored("x/y/foo.img", pats)
    assert m.path_is_ignored("pkg/build/lib.py", pats)
    assert not m.path_is_ignored("src/eigsep/io.py", pats)
    assert not m.path_is_ignored("docs/cmt.pdf", pats)
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_build_field_kb.py -v`
Expected: FAIL — `FileNotFoundError` (script missing).

- [ ] **Step 3: Create the script with the two functions**

Create `scripts/build-field-kb.py`:

```python
"""Assemble the offline field-KB corpus for the AnythingLLM operator agent.

Gathers the curated operator KB (docs/field-kb, minus the anythingllm/
config), the interface ICDs (docs/interface), the operator runbooks
(docs/operator), and the source + doc trees of the blessed field-stack
siblings into a single folder ready to import into AnythingLLM. Stamps
CORPUS-MANIFEST.md with the release version, build date, and the
resolved git commit of each tree so the agent can report which release
the corpus matches.

Sibling trees are enumerated from manifest.toml (the same packages +
git-backed hardware entries the image build clones), so the corpus
tracks the blessed tuple. Run on a machine where the siblings are
checked out under --src-root (default: the repo's parent directory).
"""

from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from eigsep_field import load_manifest  # noqa: E402


def read_ignore(path: Path) -> list[str]:
    """Return non-comment, non-blank glob patterns from a corpus.ignore."""
    out: list[str] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        out.append(line)
    return out


def path_is_ignored(relpath: str, patterns: list[str]) -> bool:
    """True if relpath matches any ignore pattern.

    A trailing-slash pattern (``build/``) matches that directory anywhere
    in the path. Other patterns are fnmatch-ed against the full relative
    path and against each individual path component (so ``*.img`` matches
    at any depth).
    """
    parts = Path(relpath).parts
    for pat in patterns:
        if pat.endswith("/"):
            if pat.rstrip("/") in parts:
                return True
            continue
        if fnmatch.fnmatch(relpath, pat):
            return True
        if any(fnmatch.fnmatch(p, pat) for p in parts):
            return True
    return False
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_build_field_kb.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add scripts/build-field-kb.py tests/test_build_field_kb.py
git commit -m "feat(build-field-kb): ignore-list parsing and path matching"
```

---

## Task 8: build-field-kb.py — filtered copy + sibling enumeration

**Files:**
- Modify: `scripts/build-field-kb.py`
- Modify: `tests/test_build_field_kb.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_build_field_kb.py`:

```python
def test_copy_filtered_excludes_ignored(tmp_path):
    m = _load_module()
    src = tmp_path / "src"
    (src / ".git").mkdir(parents=True)
    (src / ".git" / "x").write_text("nope")
    (src / "pkg").mkdir()
    (src / "pkg" / "io.py").write_text("keep")
    (src / "big.img").write_text("nope")
    dst = tmp_path / "dst"
    n = m.copy_filtered(src, dst, [".git/", "*.img"])
    assert (dst / "pkg" / "io.py").read_text() == "keep"
    assert not (dst / ".git").exists()
    assert not (dst / "big.img").exists()
    assert n == 1


def test_sibling_sources_from_manifest(tmp_path):
    m = _load_module()
    manifest = {
        "packages": {
            "eigsep_redis": {
                "source": "https://x/eigsep_redis", "tag": "v2.3.0",
            },
            "picohost": {
                "source": "https://x/pico-firmware", "tag": "v3.6.0",
                "clone_path": "pico-firmware", "package_path": "picohost",
            },
        },
        "hardware": {
            "casperfpga": {
                "source": "https://x/casperfpga", "tag": "v0.7.2",
            },
            "lgpio": {"version": "0.2.2.0"},  # no source -> skipped
        },
    }
    src_root = tmp_path
    srcs = m.sibling_sources(manifest, src_root)
    names = {s.name: s for s in srcs}
    assert "lgpio" not in names              # PyPI sdist, no tree
    assert names["eigsep_redis"].clone_dir == src_root / "eigsep_redis"
    assert names["picohost"].clone_dir == src_root / "pico-firmware"
    assert names["picohost"].package_dir == src_root / "pico-firmware" / "picohost"
    assert names["casperfpga"].clone_dir == src_root / "casperfpga"
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_build_field_kb.py -v`
Expected: FAIL — `copy_filtered` / `sibling_sources` not defined.

- [ ] **Step 3: Add the functions**

Append to `scripts/build-field-kb.py` (after `path_is_ignored`):

```python
from dataclasses import dataclass


def copy_filtered(src: Path, dst: Path, patterns: list[str]) -> int:
    """Copy src/ into dst/, skipping ignored paths. Returns files copied."""
    count = 0
    for f in sorted(src.rglob("*")):
        if not f.is_file():
            continue
        rel = f.relative_to(src).as_posix()
        if path_is_ignored(rel, patterns):
            continue
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, target)
        count += 1
    return count


@dataclass(frozen=True)
class SiblingSource:
    """A sibling tree to gather into the corpus.

    ``clone_dir`` is the on-disk repo root under --src-root; ``package_dir``
    is the Python project dir (clone_dir + package_path), used to keep the
    copy focused on code+docs and avoid vendored SDK/submodule bloat.
    """

    name: str
    clone_dir: Path
    package_dir: Path


def sibling_sources(manifest: dict, src_root: Path) -> list[SiblingSource]:
    """Enumerate git-backed siblings to gather, mirroring the image build.

    Includes every [packages.*] entry and every [hardware.*] entry that
    has a ``source`` (PyPI-sdist hardware entries like lgpio have no tree
    and are skipped).
    """
    out: list[SiblingSource] = []
    entries: list[tuple[str, dict]] = []
    entries += list(manifest.get("packages", {}).items())
    entries += [
        (n, e)
        for n, e in manifest.get("hardware", {}).items()
        if "source" in e
    ]
    for name, entry in entries:
        clone_dir = src_root / entry.get("clone_path", name)
        sub = entry.get("package_path")
        package_dir = clone_dir / sub if sub else clone_dir
        out.append(SiblingSource(name, clone_dir, package_dir))
    return out
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_build_field_kb.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add scripts/build-field-kb.py tests/test_build_field_kb.py
git commit -m "feat(build-field-kb): filtered copy + manifest sibling enumeration"
```

---

## Task 9: build-field-kb.py — assemble + CORPUS-MANIFEST stamp + CLI

**Files:**
- Modify: `scripts/build-field-kb.py`
- Modify: `tests/test_build_field_kb.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_build_field_kb.py`:

```python
def _fake_repo(tmp_path):
    """A minimal eigsep-field-shaped repo + one sibling under src_root."""
    repo = tmp_path / "eigsep-field"
    (repo / "docs" / "field-kb" / "anythingllm").mkdir(parents=True)
    (repo / "docs" / "field-kb" / "topology.md").write_text("# topo\n")
    (repo / "docs" / "field-kb" / "anythingllm" / "setup.md").write_text("x")
    (repo / "docs" / "interface").mkdir(parents=True)
    (repo / "docs" / "interface" / "redis-keys.md").write_text("# keys\n")
    (repo / "docs" / "operator").mkdir(parents=True)
    (repo / "docs" / "operator" / "laptop.md").write_text("# laptop\n")
    (repo / "src").mkdir()
    (repo / "src" / "ef.py").write_text("# code\n")
    (repo / "firmware").mkdir()
    (repo / "firmware" / "loader.py").write_text("# rfsoc\n")
    (repo / "README.md").write_text("# eigsep-field\n")
    # a sibling next to the repo
    sib = tmp_path / "eigsep_redis"
    (sib / "src").mkdir(parents=True)
    (sib / "src" / "r.py").write_text("# redis\n")
    (sib / "big.img").write_text("BLOB")
    return repo


def test_build_assembles_corpus_and_stamp(tmp_path):
    m = _load_module()
    repo = _fake_repo(tmp_path)
    manifest = {
        "release": "2026.4.0",
        "packages": {
            "eigsep_redis": {"source": "https://x", "tag": "v2.3.0"}
        },
    }
    out = tmp_path / "corpus"
    m.build(
        manifest=manifest,
        repo_root=repo,
        src_root=tmp_path,
        out_dir=out,
        patterns=[".git/", "*.img"],
        build_date="2026-06-15",
    )
    # curated KB copied, anythingllm/ config excluded from the corpus
    assert (out / "kb" / "topology.md").exists()
    assert not (out / "kb" / "anythingllm" / "setup.md").exists()
    # ICDs + operator docs copied
    assert (out / "interface" / "redis-keys.md").exists()
    assert (out / "operator" / "laptop.md").exists()
    # this repo's code + firmware copied under repos/eigsep-field
    assert (out / "repos" / "eigsep-field" / "src" / "ef.py").exists()
    assert (out / "repos" / "eigsep-field" / "firmware" / "loader.py").exists()
    # sibling copied, blob excluded
    assert (out / "repos" / "eigsep_redis" / "src" / "r.py").exists()
    assert not (out / "repos" / "eigsep_redis" / "big.img").exists()
    # stamp present and names the release
    stamp = (out / "CORPUS-MANIFEST.md").read_text()
    assert "2026.4.0" in stamp
    assert "2026-06-15" in stamp
    assert "eigsep_redis" in stamp


def test_main_runs_end_to_end(tmp_path, monkeypatch):
    m = _load_module()
    repo = _fake_repo(tmp_path)
    monkeypatch.setattr(m, "REPO_ROOT", repo)
    monkeypatch.setattr(
        m, "load_manifest",
        lambda: {"release": "2026.4.0",
                 "packages": {"eigsep_redis": {"source": "x", "tag": "v2.3.0"}}},
    )
    out = tmp_path / "corpus"
    rc = m.main(["--src-root", str(tmp_path), "--out", str(out)])
    assert rc == 0
    assert (out / "CORPUS-MANIFEST.md").exists()
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_build_field_kb.py -v`
Expected: FAIL — `build` / `main` not defined.

- [ ] **Step 3: Add `git_commit`, `write_stamp`, `build`, `main`**

Append to `scripts/build-field-kb.py`:

```python
IGNORE_FILE = REPO_ROOT / "docs" / "field-kb" / "anythingllm" / "corpus.ignore"


def git_commit(path: Path) -> str | None:
    """Best-effort short commit of a checked-out tree (None if not a repo)."""
    try:
        out = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, check=True,
        )
        return out.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def write_stamp(
    out_dir: Path, manifest: dict, commits: dict[str, str | None],
    build_date: str,
) -> None:
    lines = [
        "# CORPUS-MANIFEST",
        "",
        f"- release: {manifest.get('release', 'unknown')}",
        f"- built: {build_date}",
        "",
        "## Source trees",
        "",
        "| repo | commit |",
        "|------|--------|",
    ]
    for name in sorted(commits):
        lines.append(f"| {name} | {commits[name] or 'unknown'} |")
    (out_dir / "CORPUS-MANIFEST.md").write_text("\n".join(lines) + "\n")


def build(
    *, manifest: dict, repo_root: Path, src_root: Path, out_dir: Path,
    patterns: list[str], build_date: str,
) -> None:
    """Assemble the corpus folder at out_dir."""
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    # 1. curated KB (minus the anythingllm/ operator config)
    copy_filtered(
        repo_root / "docs" / "field-kb",
        out_dir / "kb",
        patterns + ["anythingllm/"],
    )
    # 2. interface ICDs + operator docs
    copy_filtered(repo_root / "docs" / "interface", out_dir / "interface", patterns)
    copy_filtered(repo_root / "docs" / "operator", out_dir / "operator", patterns)

    # 3. this repo's own code/firmware/readme (eigsep-field is in scope)
    ef = out_dir / "repos" / "eigsep-field"
    for sub in ("src", "firmware"):
        if (repo_root / sub).is_dir():
            copy_filtered(repo_root / sub, ef / sub, patterns)
    if (repo_root / "README.md").exists():
        ef.mkdir(parents=True, exist_ok=True)
        shutil.copy2(repo_root / "README.md", ef / "README.md")

    # 4. blessed field-stack siblings: package dir + docs/ + top-level md/rst
    commits: dict[str, str | None] = {"eigsep-field": git_commit(repo_root)}
    for s in sibling_sources(manifest, src_root):
        if not s.clone_dir.is_dir():
            print(f"  WARN missing sibling tree: {s.clone_dir}", file=sys.stderr)
            commits[s.name] = None
            continue
        dest = out_dir / "repos" / s.name
        if s.package_dir.is_dir():
            copy_filtered(s.package_dir, dest, patterns)
        if (s.clone_dir / "docs").is_dir():
            copy_filtered(s.clone_dir / "docs", dest / "docs", patterns)
        for doc in sorted(s.clone_dir.glob("*.md")) + sorted(
            s.clone_dir.glob("*.rst")
        ):
            dest.mkdir(parents=True, exist_ok=True)
            shutil.copy2(doc, dest / doc.name)
        commits[s.name] = git_commit(s.clone_dir)

    # 5. provenance
    write_stamp(out_dir, manifest, commits, build_date)
    print(f"corpus written to {out_dir}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--src-root", default=str(REPO_ROOT.parent),
        help="dir holding the sibling checkouts (default: repo parent)",
    )
    ap.add_argument(
        "--out", default=str(REPO_ROOT / "out" / "field-kb-corpus"),
        help="output corpus directory",
    )
    ap.add_argument(
        "--from-worktree", action="store_true",
        help="build from local checkouts as-is (default; reserved for "
             "future SHA-pinned mode)",
    )
    args = ap.parse_args(argv)
    build(
        manifest=load_manifest(),
        repo_root=REPO_ROOT,
        src_root=Path(args.src_root),
        out_dir=Path(args.out),
        patterns=read_ignore(IGNORE_FILE),
        build_date=dt.date.today().isoformat(),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_build_field_kb.py -v`
Expected: PASS (6 passed).

- [ ] **Step 5: Lint + full test suite**

Run: `ruff check scripts/build-field-kb.py tests/test_build_field_kb.py tests/test_field_kb.py`
Expected: no errors (line-length 79; the late import is covered by the `scripts/*.py = ["E402"]` per-file ignore).

Run: `python -m pytest -q`
Expected: all tests pass (existing suite + the two new files).

- [ ] **Step 6: Commit**

```bash
git add scripts/build-field-kb.py tests/test_build_field_kb.py
git commit -m "feat(build-field-kb): assemble corpus + CORPUS-MANIFEST stamp + CLI"
```

---

## Task 10: Real-corpus smoke run + bake-off (manual, operator-run)

**Files:** none (validation task).

- [ ] **Step 1: Build the corpus against the real siblings**

Run from the repo root (siblings checked out under the parent dir):

```bash
python scripts/build-field-kb.py --out ./out/field-kb-corpus
```

Expected: prints `corpus written to ./out/field-kb-corpus`, no `WARN
missing sibling tree` lines for `eigsep_redis`, `picohost`/`pico-firmware`,
`eigsep-vna`/`CMT-VNA`, `eigsep_observing`, `pyvalon`, `casperfpga`.

- [ ] **Step 2: Eyeball the corpus**

```bash
cat ./out/field-kb-corpus/CORPUS-MANIFEST.md
find ./out/field-kb-corpus -name '*.img' -o -name '*.npz'   # expect: nothing
find ./out/field-kb-corpus -name '*.pdf' | head             # expect: CMT manuals present
du -sh ./out/field-kb-corpus
```

Confirm: the release + per-repo commits are stamped; no large blobs leaked
in; the CMT vendor PDFs are present; total size is reasonable (tens of MB,
not GB).

- [ ] **Step 3: Install + import on the laptops**

Follow `docs/field-kb/anythingllm/setup.md` on the ThinkPad (and the
spare Ubuntu laptop): install Ollama + AnythingLLM, pull the models,
import `out/field-kb-corpus/`, paste the workspace prompt with the
release version filled in.

- [ ] **Step 4: Run the bake-off**

Work through `docs/field-kb/anythingllm/bakeoff.md`: ask the 10 questions
against `qwen2.5:7b-instruct` (and any larger candidate the laptop's RAM
allows), score grounded/correct/cited/concise, record tokens/sec, and
pick the default model.

- [ ] **Step 5: Record the decision**

Update the spec's open-question section
(`docs/superpowers/specs/2026-06-15-field-kb-anythingllm-design.md`) with
the chosen LLM + embedder and each laptop's RAM/GPU. Commit.

```bash
git add docs/superpowers/specs/2026-06-15-field-kb-anythingllm-design.md
git commit -m "docs(field-kb): record bake-off model decision"
```

---

## Self-Review

**Spec coverage (Phase 1 scope):**
- Curated KB centralized in `docs/field-kb/` — Tasks 1–6. ✅
- Glossary / FAQ / topology / runbooks anchors — glossary (T4), topology
  (T3), 4 runbooks (T5). FAQ is Phase 2 (not Phase-1 MVP per spec). ✅
- `build-field-kb.py` assembles KB + ICDs + operator + full sibling
  trees, pinned, with provenance — Tasks 7–9. ✅
- CMT PDFs shipped — corpus.ignore keeps `*.pdf`; sibling copy includes
  `docs/`; verified in T10 Step 2. ✅
- AnythingLLM config (local model/embedder, system prompt, ignore) —
  Task 6 + Task 1. ✅
- Two Linux laptops + operator-run installs — setup.md (T6), T10. ✅
- Model bake-off to settle the deferred model choice — bakeoff.md (T6),
  T10. ✅
- Out of scope held to Phase 1: no CI workflow, no refresh script, no
  code maps / hardware-note curation — deferred to Phase 2/3 plans. ✅

**Placeholder scan:** the only intentional fill-in is `<FILL IN FROM
CORPUS-MANIFEST.md>` in the workspace prompt — that is an operator
runtime value (the corpus version differs per build), documented in
setup.md Step 6, not a plan gap.

**Type consistency:** `read_ignore`, `path_is_ignored`, `copy_filtered`,
`SiblingSource(name, clone_dir, package_dir)`, `sibling_sources`,
`git_commit`, `write_stamp`, `build(*, manifest, repo_root, src_root,
out_dir, patterns, build_date)`, `main(argv)` — names and signatures are
consistent across the tests (T7–T9) and the implementation.
```
