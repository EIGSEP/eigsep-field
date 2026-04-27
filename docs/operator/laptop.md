# Operator laptop capabilities

The Pi image is self-sufficient: with no laptop attached, the Pis come
up, the dhcp-master serves DHCP and runs `chrony` with `local stratum
10`, and the cluster mutually agrees on time. The laptop is a
convenience for the operator, not a dependency for the system.

## EIGSEP private LAN address conventions

| Address       | Host                                      |
|---------------|-------------------------------------------|
| `10.10.10.10` | ground / dhcp-master Pi (published entry) |
| `10.10.10.11` | panda Pi                                  |
| `10.10.10.12` | SNAP board #1                             |
| `10.10.10.13` | SNAP board #2                             |
| `10.10.10.17` | operator laptop (any laptop, static)      |
| `.20`–`.255`  | DHCP dynamic pool                         |

`10.10.10.10` is the address collaborators should know — it's the
ground Pi.

## What the laptop needs

- **Wired Ethernet on the EIGSEP LAN.**
- **Static IP `10.10.10.17/24` on that interface, no DHCP.** The
  ground Pi does not reserve `.17` by MAC, so a DHCP-leased laptop
  would land at a random `.20`+ address. Configuring `.17` statically
  is what makes any laptop swap into `chrony`'s expected upstream
  address — if your laptop dies in the field, a backup laptop that
  follows this doc lands at the same IP and the cluster keeps full
  UTC discipline. (Linux: NetworkManager → IPv4 → Manual; macOS:
  System Settings → Network → Ethernet → Configure IPv4 → Manually.)
- **SSH client.** Reach the Pis at the addresses above.
- **(Optional) chrony serving NTP** with `allow 10.10.10.0/24`. This
  upgrades the cluster from "self-agreed" to "true UTC" while the
  laptop is connected. Without it, the dhcp-master falls back to
  `local stratum 10` and the cluster keeps mutually agreed time, just
  not pinned to UTC.

That's it. Nothing else is required on the laptop for the field stack
to function — observing software, contract tests, and image-flashing
all run from the Pis or from a build host elsewhere.
