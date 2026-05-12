# Sourcing and deploying a new Pi

The runbook for adding a new Raspberry Pi to the EIGSEP field stack.
Cross-references where state needs to land in this repo so nothing
drifts back onto a personal machine.

## 1. Decide the role

Each Pi runs one role:

- `panda` — observing front-end (picohost, cmtvna, etc). Pinned to
  `10.10.10.11`.
- `backend` — Redis + observer + LAN's DHCP + NTP server. Pinned to
  `10.10.10.10`. Exactly one per LAN.

The role-applier pins eth0 to the role's static IP (see
`ROLE_STATIC_IPS` in `src/eigsep_field/cli.py`), so a fresh Pi is
reachable at its conventional address from first boot — no
DHCP-reservation-by-MAC step required.

## 2. Flash the latest image

```
./scripts/flash-image.sh                # uses v{manifest.release}
./scripts/flash-image.sh v2026-5.0-rc1  # or pin to a specific tag
```

This downloads the release's split image parts, reassembles them,
verifies sha256, decompresses, and prints (does not run) the `dd`
command. Run the printed `dd` after confirming the SD card device with
`lsblk`.

The image is uniform across roles and across Pi 4 / Pi 5; per-Pi state
is set by `/boot/firmware/eigsep-role.conf`. Today panda runs on a Pi 4
and backend on a Pi 5, but role is decoupled from hardware — either
role can run on either Pi.

## 2.5. (Pi 5 only) Install the RTC coin cell

The Pi 5 has an onboard RTC chip but it only persists across power
cycles if a CR1220 coin cell is installed on the J5 header. Without
it, the Pi 5 behaves like the Pi 4 — no real RTC, and on boot the
clock comes from the last `fake-hwclock` value (i.e. last shutdown
time, which the rest of the cluster will then agree on for the
session). For any deployment where wall-clock accuracy matters, fit
the cell at commissioning time.

After installing the cell and booting the Pi with a correct system
clock (e.g. while still on a network with chrony reaching public NTP),
write the time to the RTC once:

```
sudo hwclock --systohc
sudo hwclock --show          # confirm reads back as wall time
```

From then on, `chrony`'s `rtcsync` directive keeps the RTC tracking
the disciplined system clock automatically. See `laptop.md` for how
the coin cell and the operator laptop combine to give the cluster its
time discipline.

## 3. Set the role on first boot

After running `dd`, leave the SD card in the reader — Linux auto-mounts
the FAT boot partition (label `bootfs`) at `/media/$USER/bootfs/`.
Create `eigsep-role.conf` there before first power-on:

```
echo "role = panda" > /media/$USER/bootfs/eigsep-role.conf   # or "backend"
```

On the Pi this same partition is mounted at `/boot/firmware/`, so the
file ends up at `/boot/firmware/eigsep-role.conf` once the SD card is
in the Pi — but the operator never touches that path directly.

`eigsep-first-boot.service` reads it on first boot, enables the
matching services, pins eth0 to the role's static IP, and
self-disables.

## 4. Verify

On the new Pi:

```
eigsep-field info       # release + installed package versions
eigsep-field doctor     # role + service health
eigsep-field services list
```

From the operator laptop or backend Pi, confirm reachability at the
conventional address (`10.10.10.10` for backend, `10.10.10.11` for
panda).

## Address conventions

See [`laptop.md`](laptop.md) for the full table. The Pi assignments
relevant here:

| Address       | Host                                       |
|---------------|--------------------------------------------|
| `10.10.10.10` | backend Pi (role-pinned static)            |
| `10.10.10.11` | panda Pi (role-pinned static)              |
| `10.10.10.12` | active SNAP board (DHCP reservation; both physical units share this address — spare-only, never powered simultaneously) |

`.10` is the published entry point. Collaborators reach the system
there.
