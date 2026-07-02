# firmware/rfsoc/

Operator runbook (field sequence, troubleshooting):
[`docs/operator/rfsoc.md`](../../docs/operator/rfsoc.md). This page
covers where the artifacts come from and why.

RFSoC firmware + waveform artifacts. The blobs themselves are not
committed — they come from `eigsep_dac` GitHub Releases, pinned by
`[firmware.rfsoc]` in the top-level `manifest.toml` (the per-directory
manifest mirror is gone; the top-level manifest is the single source
of truth). The image stages the pinned asset at
`/opt/eigsep/firmware/rfsoc/` on the backend Pi.

The host programmer code (previously vendored here as `loader.py`) now
lives in the installable `eigsep_dac` package, pinned in the top-level
`manifest.toml` under `[hardware.eigsep_dac]`. Its tag must equal
`[firmware.rfsoc].tag` — the waveform/firmware bundle and the
programmer are produced together.

## Where the programmer runs

`eigsep_dac` is a **hardware** package — not a runtime dep of the
`eigsep-field` meta wheel. It runs on the RFSoC, not the Pi. The
wheelhouse carries its wheel so a field operator can rsync it to the
RFSoC without internet:

```bash
# On the Pi (or anywhere with the wheelhouse)
scp /opt/eigsep/wheels/eigsep_dac-*.whl rfsoc:/tmp/

# On the RFSoC (py3.10 conda env; the wheel is pure Python)
/home/eigsep/miniconda3/envs/py310/bin/python -m pip install --no-index --find-links /tmp /tmp/eigsep_dac-*.whl
```

The wheel is pure Python (`py3-none-any`), so the RFSoC's Python 3.10
conda env installs it even though the wheelhouse resolve targets the
manifest's newer Python — no compiled cp3xx wheels are involved
(numpy and casperfpga are already on the board).

## Programming both DACs (2026 firmware)

`[firmware.rfsoc]` pins `rfsoc_2026.tar.gz` from the eigsep_dac
release: the dual-BRAM loader script, the 2026 `.fpg`/`.dtbo` pair,
and both dual-channel waveform npz files. Unpacking it on the board
reproduces the tested `rfsoc_2026/` layout (the `.dtbo` must sit next
to the `.fpg`; the on-board casperfpga checkout is the one piece not
bundled):

```bash
# On the Pi
scp /opt/eigsep/firmware/rfsoc/rfsoc_2026.tar.gz rfsoc:/home/eigsep/eigsep/

# On the RFSoC
cd /home/eigsep/eigsep && tar xzf rfsoc_2026.tar.gz
sudo /home/eigsep/miniconda3/envs/py310/bin/python \
    rfsoc_2026/dual_bram_mts_npz_loader.py \
    --fpg rfsocdactut_2026_2026-05-21_1047.fpg \
    --npz interweave_dac_both_x3.npz --once
```

See eigsep_dac's README ("Programming both DACs (2026 firmware)") for
the full directions — MTS retries, `--once` semantics, npz schema.

## Flash (2025 single-DAC flow)

The boot-time flow the board still runs today: the `eigsep-dac-program`
console script (from the wheel) loads a single-channel waveform npz
onto DAC2. The RFSoC's boot systemd unit invokes the same entry point
via `rfsocdac.py`. Hot-fixing in the field means rsync a newer wheel
to the RFSoC and `pip install --upgrade`; no re-image required.
