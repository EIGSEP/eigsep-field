# firmware/rfsoc/

RFSoC bitstream artifact. The `.npz` itself is not committed — it's in
GitHub Releases. This directory carries:

- `manifest.toml` — version (date), asset filename, source commit, sha256

The host programmer code (previously vendored here as `loader.py`) now
lives in the installable `eigsep_dac` package, pinned in the top-level
`manifest.toml` under `[hardware.eigsep_dac]`. Its tag must match the
`commit` pinned in `[firmware.rfsoc_bitstream]` — the bitstream and the
programmer are produced together.

## Where the programmer runs

`eigsep_dac` is a **hardware** package — not a runtime dep of the
`eigsep-field` meta wheel. It runs on the RFSoC, not the Pi. The
wheelhouse carries its wheel so a field operator can rsync it to the
RFSoC without internet:

```bash
# On the Pi (or anywhere with the wheelhouse)
scp /opt/eigsep/wheels/eigsep_dac-*.whl rfsoc:/tmp/
scp /opt/eigsep/wheels/casperfpga-*.whl rfsoc:/tmp/
scp /opt/eigsep/firmware/rfsoc/*.npz rfsoc:/opt/eigsep/firmware/rfsoc/

# On the RFSoC
pip install --no-index --find-links /tmp /tmp/eigsep_dac-*.whl
```

## Flash

After the wheel is installed on the RFSoC, the `eigsep-dac-program`
console script loads a bitstream npz:

```bash
eigsep-dac-program --ip <board> \
    --npz /opt/eigsep/firmware/rfsoc/<asset>.npz
```

The RFSoC's boot systemd unit invokes the same entry point (via
`rfsocdac.py` in eigsep_dac, which forwards to
`eigsep_dac.program_board.main`). Hot-fixing in the field means rsync
a newer wheel to the RFSoC and `pip install --upgrade`; no re-image
required.
