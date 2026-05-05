# Sourcing and deploying a new Pi

The runbook for adding a new Raspberry Pi to the EIGSEP field stack.
Cross-references where state needs to land in this repo so nothing
drifts back onto a personal machine.

## 1. Decide the role

Each Pi runs one role:

- `panda` — observing front-end (picohost, cmtvna, etc).
- `backend` — Redis + observer.
- One Pi additionally has `dhcp = true`, making it the LAN's
  dhcp-master and NTP server. Today this is the ground Pi.

## 2. Flash the latest image

```
./scripts/flash-image.sh                # uses manifest.toml [image].tag
./scripts/flash-image.sh v2026-5.0-rc1  # or pin to a specific tag
```

This downloads the release's split image parts, reassembles them,
verifies sha256, decompresses, and prints (does not run) the `dd`
command. Run the printed `dd` after confirming the SD card device with
`lsblk`.

The image is uniform across roles and across Pi 4 / Pi 5; per-Pi state
is set by `/boot/eigsep-role.conf`. Today panda runs on a Pi 4 and
backend on a Pi 5, but role is decoupled from hardware — either role
can run on either Pi.

## 3. Set the role on first boot

Create `/boot/eigsep-role.conf` on the Pi's boot partition before
first power-on:

```
role = panda          # or "backend"
dhcp = false          # or "true" on exactly one Pi per LAN
```

`eigsep-first-boot.service` reads it on first boot, enables the
matching services, pins eth0 to `10.10.10.10/24` if `dhcp = true`,
and self-disables.

## 4. Capture the MAC and reserve the IP

**This is the step easy to forget when sourcing hardware.** Boot the
Pi onto the LAN once, then:

```
# On the dhcp-master:
journalctl -u isc-dhcp-server | grep DHCPACK | tail
# or:
arp -an | grep 10.10.10.
```

Capture the new Pi's MAC. Then add (or uncomment) the reservation in
[`image/pi-gen-config/stage-eigsep/files/dhcp/dhcpd.conf`](../../image/pi-gen-config/stage-eigsep/files/dhcp/dhcpd.conf):

```
host panda {
  hardware ethernet AA:BB:CC:DD:EE:FF;
  fixed-address 10.10.10.11;
}
```

Open a PR with the change. After merge, rebuild the image at the next
release; the Pi will land at its conventional address from then on.

(Until the reservation is merged + redeployed, the Pi will get a
dynamic-pool address `.20`+ and other code that expects to reach it
at the conventional address won't work.)

## 5. Verify

On the new Pi:

```
eigsep-field info       # release + installed package versions
eigsep-field doctor     # role + service health
eigsep-field services list
```

On the dhcp-master, confirm the new Pi got its expected lease:

```
journalctl -u isc-dhcp-server -f
```

## Address conventions

See [`laptop.md`](laptop.md) for the full table. The Pi reservations
relevant here:

| Address       | Host                                  |
|---------------|---------------------------------------|
| `10.10.10.10` | ground / dhcp-master Pi (static)      |
| `10.10.10.11` | panda Pi (DHCP reservation)           |
| `10.10.10.12` | active SNAP board (DHCP reservation; both physical units share this address — spare-only, never powered simultaneously) |

`.10` is the published entry point. Collaborators reach the system
there.
