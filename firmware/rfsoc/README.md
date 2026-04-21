# firmware/rfsoc/

RFSoC bitstream artifact. The `.npz` itself is not committed — it's in
GitHub Releases. This directory carries:

- `manifest.toml` — version (date), asset filename, source commit, sha256
- `loader.py` — **vendored** from `eigsep_dac` at the pinned commit. The
  vendor insulates the field from `eigsep_dac`'s ongoing development
  churn; when we bump the bitstream, we re-vendor this file from the same
  commit.

## Why vendor rather than depend

`eigsep_dac` is a mixed analysis + code repo without a release cadence or
stable API. We only need the `.npz` loader script, not the notebooks and
analysis scaffolding. Pinning by commit SHA + vendoring `loader.py` gives
us deterministic behavior without taking a dependency on an unstable
package.

When `eigsep_dac` eventually carves out a stable `eigsep_dac.bitstream`
subpackage with a published API, promote it from vendor to dep and delete
this loader.

## Flash

```bash
python3 /opt/eigsep/firmware/rfsoc/loader.py \
    /opt/eigsep/firmware/rfsoc/<asset>.npz
```
