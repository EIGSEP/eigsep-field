# image/

pi-gen recipe that bakes the blessed EIGSEP field stack into a Raspberry Pi
image. The `.img.xz` artifact is published to the GitHub Release for the
tagged manifest version.

## Layout

- `pi-gen-config/config` — pi-gen top-level config (release, hostname,
  stage list).
- `pi-gen-config/stage-eigsep/` — custom stage layered on top of stage2-lite.
  - `prerun.sh` — copies the prior stage's rootfs.
  - `00-run.sh` — installs apt packages, drops the offline wheelhouse, runs
    `pip install --no-index --find-links /opt/eigsep/wheels eigsep-field`,
    installs systemd units.
  - `files/` — staged at build time by `.github/workflows/image.yml`:
    - `wheels/` — untarred from the wheelhouse Release asset.
    - `firmware/pico/*.uf2` and `firmware/rfsoc/*.npz` — pulled by
      `scripts/fetch_firmware.py`.
    - `etc-eigsep/manifest.toml` — copy of the blessed manifest.
    - `systemd/*.service` + `systemd/eigsep.target`.

## Login credentials

The image creates a single user, `eigsep`. Its password is set at build
time from the **`IMAGE_FIRST_USER_PASS`** repo secret (see
`.github/workflows/image.yml`'s "Layer stage-eigsep into pi-gen" step).

- To **rotate** or look up the secret: repo Settings → Secrets and
  variables → Actions → `IMAGE_FIRST_USER_PASS`. GitHub stores secrets
  write-only — you can overwrite the value or delete it, but you cannot
  read it back through the UI. Whoever set it last is the only person
  who knows the value; if that's lost, rotate.
- The CI workflow **fails fast** if the secret is unset, so a missing
  rotation never silently ships pi-gen's default `raspberry`.
- For a **manual local build** you must export `FIRST_USER_PASS`
  yourself before invoking pi-gen — the local build path doesn't read
  the GitHub secret.

## Redis on the field LAN

The image ships a Redis override at
`/etc/redis/redis.conf.d/eigsep.conf` that binds Redis to all
interfaces (`bind 0.0.0.0 -::`) and disables `protected-mode`. This is
required because the writer (`eigsep-observe`) reads from the panda Pi
and the SNAP-host Pi simultaneously, and is also what lets an operator
laptop plug into the field switch and run a live plotter or a parallel
writer. It is safe because the field LAN (10.10.10.0/24) is physically
isolated with no internet uplink. Do **not** copy this config to a Pi
on a public network without adding `requirepass` first.

## Build locally

Requires linux with root (for `losetup`/`mount`) or a VM. See
https://github.com/RPi-Distro/pi-gen for full instructions.

```bash
# Stage wheelhouse + firmware into files/ first (or let the workflow do it).
mkdir -p image/pi-gen-config/stage-eigsep/files/{wheels,firmware,systemd,etc-eigsep}
tar -C image/pi-gen-config/stage-eigsep/files/wheels -xJf wheels-linux_aarch64.tar.xz
python3 scripts/fetch_firmware.py manifest.toml image/pi-gen-config/stage-eigsep/files/firmware
cp manifest.toml image/pi-gen-config/stage-eigsep/files/etc-eigsep/manifest.toml
cp image/pi-gen-config/stage-eigsep/files/systemd/*.service \
   image/pi-gen-config/stage-eigsep/files/systemd/*.target \
   image/pi-gen-config/stage-eigsep/files/systemd/ 2>/dev/null || true

git clone --depth=1 --branch arm64 https://github.com/RPi-Distro/pi-gen.git /tmp/pi-gen
cp -r image/pi-gen-config/stage-eigsep /tmp/pi-gen/stage-eigsep
cp image/pi-gen-config/config /tmp/pi-gen/config
cd /tmp/pi-gen && sudo ./build.sh
```

Output: `deploy/*.img.xz` in the pi-gen tree.
