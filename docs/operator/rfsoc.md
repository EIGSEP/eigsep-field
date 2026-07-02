# RFSoC field operations

The runbook for the RFSoC2x2 transmitter at the field site. The RFSoC
is a standalone non-Pi system on the LAN at `10.10.10.13` (DHCP
reservation); it is not covered by roles, `eigsep-field doctor`, or
the image — everything here is operator-driven from the backend Pi.

Deeper background (MTS behavior, npz schema, waveform generation)
lives in the eigsep_dac repo's README; this page is the field
sequence only.

## What the board does on boot

The RFSoC boots into **last year's setup**: a systemd unit runs
`rfsocdac.py` (from the installed `eigsep_dac` package), which
transmits the 2025 single-channel waveform on the **DAC2 output
only**. Transmitting on **both** DAC outputs requires programming the
2026 firmware after boot — every boot; it does not persist.

## Where the artifacts are

The backend Pi image carries everything (no internet needed):

| On the backend Pi                            | What it is                            |
| -------------------------------------------- | ------------------------------------- |
| `/opt/eigsep/firmware/rfsoc/rfsoc_2026.tar.gz` | loader + 2026 fpg/dtbo + waveform npz |
| `/opt/eigsep/wheels/eigsep_dac-*.whl`          | host programmer package (pure Python) |

Both are pinned in `manifest.toml` (`[firmware.rfsoc]` and
`[hardware.eigsep_dac]`, same tag) and sha256-verified at image build.

## Programming both DACs (2026 firmware)

```bash
# On the backend Pi
scp /opt/eigsep/firmware/rfsoc/rfsoc_2026.tar.gz eigsep@10.10.10.13:/home/eigsep/eigsep/

# On the RFSoC (ssh eigsep@10.10.10.13)
cd /home/eigsep/eigsep && tar xzf rfsoc_2026.tar.gz
cd rfsoc_2026
sudo /home/eigsep/miniconda3/envs/py310/bin/python \
    dual_bram_mts_npz_loader.py \
    --fpg rfsocdactut_2026_2026-05-21_1047.fpg \
    --npz interweave_dac_both_x3.npz \
    --once
```

Notes:

- The `.dtbo` must stay in the same directory as the `.fpg` —
  unpacking the tarball guarantees that; don't move files around.
- The loader needs the on-board casperfpga checkout at
  `/home/eigsep/eigsep/rfsoc_2026/casperfpga`. It survives the
  `tar xzf` (the bundle has no `casperfpga/` member, so nothing is
  overwritten). The loader prints which casperfpga it imported at
  startup — check that line if anything looks off.
- `--once` programs both DACs and exits. Without it the loader keeps
  polling the `wave_form` select register and reloads on change.
- MTS can fail on a given FPGA load; the loader reprograms and retries
  by itself (up to `--max-fpga-reloads`, default 5). Let it run.
- To transmit the circular-polarization waveform instead, pass
  `--npz circular.npz` (also in the bundle).

## Hot-fixing the host programmer

The 2025 boot flow comes from the `eigsep_dac` wheel. To update it in
the field:

```bash
# On the backend Pi
scp /opt/eigsep/wheels/eigsep_dac-*.whl eigsep@10.10.10.13:/tmp/

# On the RFSoC (py3.10 conda env; the wheel is pure Python)
/home/eigsep/miniconda3/envs/py310/bin/pip install \
    --no-index --find-links /tmp --upgrade /tmp/eigsep_dac-*.whl
```

No re-image required. Note `eigsep-dac-program --help` only works on
the board — the entry point imports casperfpga before parsing
arguments, so it fails on machines without it.

## Troubleshooting

### Board unreachable — serial console

1. Micro-USB from the laptop to the RFSoC.
2. `sudo minicom -D /dev/ttyUSB1 -b 115200`, then hit enter for a
   login prompt.
3. Two prompts appear in sequence: `cuspl` first, then `eigsep`.
   Enter a **wrong password at the `cuspl` prompt** to fall through
   to the `eigsep` prompt — that is the real login. The `eigsep`
   password comes from the team out-of-band; it is not in any repo.

### Clock sanity

Sample clock must read **250 MHz**. A reading of 245.76 MHz means a
reference-clock problem — fix it before trusting any output.

### Is it even on? (12 V supply current)

| State     | Current |
| --------- | ------- |
| RFSoC on  | 1.37 A  |
| RFSoC off | 0.10 A  |

(Measured with three 15 V amplifiers in the chain, all at 12 V.)
