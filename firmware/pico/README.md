# firmware/pico/

Pico firmware artifacts. The `.uf2` blobs themselves are **not** committed —
they live in GitHub Releases. This directory tracks:

- `manifest.toml` — version / asset filename / sha256 / source tag
- build / flash notes (below)

The image build workflow (`.github/workflows/image.yml`) downloads the
blob via `scripts/fetch_firmware.py` and stages it under
`/opt/eigsep/firmware/pico/` on the final image. On a running Pi,
`eigsep-field doctor` verifies the on-disk sha256 matches the manifest.

## Flash manually

```bash
picotool load -f /opt/eigsep/firmware/pico/<asset>.uf2
picotool reboot
```

## Source

The firmware source and its CI live at
[EIGSEP/pico-firmware](https://github.com/EIGSEP/pico-firmware). Build
artifacts are attached to each tagged release there; copy the sha256 into
this repo's manifest when bumping.
