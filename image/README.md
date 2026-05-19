# image/

pi-gen recipe that bakes the blessed EIGSEP field stack into a Raspberry Pi
image. The `.img.xz` artifact is published to the GitHub Release for the
tagged manifest version.

## Layout

- `pi-gen-config/config` — pi-gen top-level config (release, hostname,
  stage list).
- `pi-gen-config/stage-eigsep/` — custom stage layered on top of stage2-lite.
  - `prerun.sh` — copies the prior stage's rootfs.
  - `EXPORT_IMAGE` — marker that tells pi-gen to deploy *this* stage's
    rootfs as the published `.img` (without it, pi-gen ships stage2's
    stock Lite image instead).
  - `00-eigsep-install/` — sub-stage directory; pi-gen only executes
    `\d\d-run.sh` scripts inside numbered sub-directories of a stage,
    not at the stage root.
    - `00-run.sh` — installs apt packages, drops the offline wheelhouse,
      runs `pip install --no-index --find-links /opt/eigsep/wheels
      eigsep-field`, installs systemd units.
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

## Getting WiFi on a DEV image

DEV images (any non-blessed build — workflow_dispatch, rc-style tag,
hotfix-test tag) ship with WiFi disabled, same as blessed. The image
deliberately does not auto-configure a network because the blessed
field deployment has no uplink. For lab/venue use on a DEV build, the
operator brings up WiFi by hand after first boot:

```bash
# 1. Get a shell — via the role-pinned ethernet
#    (ssh eigsep@10.10.10.10 for backend, .11 for panda) or HDMI+keyboard.

# 2. Set the wireless regulatory country (one-time; persists). Pi-gen
#    Trixie leaves the radio rfkill-blocked until a country is set —
#    without this, nmcli accepts the connection but silently fails to
#    associate. Default US; change as appropriate.
sudo raspi-config nonint do_wifi_country US
sudo rfkill unblock wifi

# 3. Add + activate. --ask prompts for the PSK so it stays out of shell
#    history and `ps` output.
sudo nmcli --ask device wifi connect <SSID>

# 4. Verify.
nmcli connection show --active
ip -4 addr show wlan0
ping -c1 1.1.1.1
```

The connection persists as a keyfile under
`/etc/NetworkManager/system-connections/<SSID>.nmconnection` (mode
0600) and reconnects on every reboot. The role-pinned `eigsep-eth0`
keyfile has `never-default=true`, so WiFi correctly takes the default
route, and on backend the `isc-dhcp-server` stays bound to eth0 only.

To remove: `sudo nmcli connection delete <SSID>`.

## Build locally

Requires linux with root (for `losetup`/`mount`) or a VM. See
https://github.com/RPi-Distro/pi-gen for full instructions.

```bash
# Stage wheelhouse + firmware into the sub-stage's files/ first (or let
# the workflow do it).
SUBSTAGE=image/pi-gen-config/stage-eigsep/00-eigsep-install
mkdir -p "$SUBSTAGE"/files/{wheels,firmware,etc-eigsep}
tar -C "$SUBSTAGE"/files/wheels -xJf wheels-linux_aarch64.tar.xz
python3 scripts/fetch_firmware.py manifest.toml "$SUBSTAGE"/files/firmware
cp manifest.toml "$SUBSTAGE"/files/etc-eigsep/manifest.toml

git clone --depth=1 --branch arm64 https://github.com/RPi-Distro/pi-gen.git /tmp/pi-gen
cp -r image/pi-gen-config/stage-eigsep /tmp/pi-gen/stage-eigsep
cp image/pi-gen-config/config /tmp/pi-gen/config
cd /tmp/pi-gen && sudo ./build.sh
```

Output: `deploy/*.img.xz` in the pi-gen tree.
