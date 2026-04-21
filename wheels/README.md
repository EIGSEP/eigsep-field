# wheels/

Empty in git. Populated by `scripts/build-wheelhouse.sh` and published as a
tarball to the GitHub Release for the tagged manifest version.

## Regenerate locally

```bash
./scripts/build-wheelhouse.sh            # defaults to manifest.toml + linux_aarch64
./scripts/build-wheelhouse.sh manifest.toml wheels linux_aarch64
```

The script runs `uv pip compile` against `pyproject.toml` (whose deps come
from `manifest.toml` via the Hatch hook), then `uv pip download` with
`--require-hashes` to fetch every wheel for the target platform. Wheels that
aren't on PyPI for the target platform are built from sdist under qemu.

## Consume the wheelhouse

```bash
pip install --no-index --find-links wheels --require-hashes \
    -r wheels/requirements.txt eigsep-field
```

Run by `scripts/install-field.sh` on the Pi. No internet required.
