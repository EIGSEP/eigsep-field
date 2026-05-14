# firmware/pico/

Pico firmware artifacts. The `.uf2` blobs themselves are **not** committed —
they live in GitHub Releases. The version, asset name, source tag, and
sha256 are pinned in the top-level `manifest.toml` `[firmware.pico]`
table; in-field rebuilds are described in `[firmware.pico.build]`.

Targets RP2350. (`eigsep_dac` uses RP2040 variants — that's a separate
artifact.)

The image build workflow (`.github/workflows/image.yml`) downloads the
blob via `scripts/fetch_firmware.py` and stages it under
`/opt/eigsep/firmware/pico/` on the final image. On a running Pi,
`eigsep-field doctor` verifies the on-disk sha256 matches the manifest.

## Flash manually

```bash
picotool load -f /opt/eigsep/firmware/pico/<asset>.uf2
picotool reboot
```

## Rebuild in field

```bash
sudo eigsep-field patch pico-firmware
```

This builds from the cloned source at `/opt/eigsep/src/pico-firmware/`
and retargets `picomanager.service` at the field UF2 via a systemd
drop-in. `eigsep-field revert pico-firmware` drops the override and
reflashes the blessed UF2.

## Source

The firmware source and its CI live at
[EIGSEP/pico-firmware](https://github.com/EIGSEP/pico-firmware). Build
artifacts are attached to each tagged release there; copy the sha256 into
this repo's `manifest.toml` when bumping.
