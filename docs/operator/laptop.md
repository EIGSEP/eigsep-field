# Operator laptop capabilities

The Pi image runs `chrony` on every Pi: the dhcp-master serves NTP on
the LAN with `local stratum 10` as a fallback so clients agree on time
even when no upstream is reachable. Whether that agreed time is
anchored to real wall-clock UTC depends on two independent pieces of
field hardware:

- **Coin cell on the Pi 5.** A CR1220 on J5 keeps the Pi 5's onboard
  RTC running across power cycles, so the cluster boots into correct
  wall time. Without it (or on a Pi 4, which has no onboard RTC at
  all), the Pi boots into the last `fake-hwclock` value — i.e. last
  shutdown time, which the cluster will then mutually agree on for
  the rest of the session. Install one when commissioning the backend
  Pi 5; see `new-pi.md`.
- **Laptop on the LAN.** A laptop's battery-backed RTC plus any
  recent internet discipline makes it a much better NTP source than a
  Pi without a coin cell, and a true-UTC source when it's online. The
  dhcp-master treats `10.10.10.17` as its preferred upstream.

Neither is strictly required for the cluster to come up and observe —
the `local stratum 10` fallback ensures internal agreement either way.
But for any campaign where wall-clock accuracy matters, plan on both:
the coin cell gives a correct boot-time floor, the laptop gives a
true-UTC ceiling.

## EIGSEP private LAN address conventions

| Address       | Host                                      |
|---------------|-------------------------------------------|
| `10.10.10.10` | ground / dhcp-master Pi (published entry) |
| `10.10.10.11` | panda Pi                                  |
| `10.10.10.12` | active SNAP board (spare-only; both units same IP) |
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
- **chrony serving NTP to the cluster.** `apt install chrony` is
  enough — Debian's stock `chrony.conf` syncs to public pools when
  there's internet, so the laptop is a real stratum-2/3 upstream
  automatically. The only laptop-side change is to authorize the LAN.
  Create `/etc/chrony/conf.d/eigsep.conf` containing:

  ```
  allow 10.10.10.0/24
  ```

  Then `sudo systemctl restart chrony`.

  **Do not** add a `local stratum N` line on the laptop. If the
  laptop is offline (no recent UTC discipline), letting it serve at
  some fixed stratum anyway would cause the dhcp-master Pi to prefer
  the laptop's potentially stale clock over its own coin-cell-backed
  RTC. The right behavior is: laptop reports stratum 16 when
  unsynchronized → dhcp-master ignores it → Pi falls back to its own
  RTC via `local stratum 10`.

## Verifying time discipline

On the laptop:

```
chronyc sources              # at least one public NTP ^*-selected
sudo ss -ulnp | grep :123    # chronyd listening on UDP/123 on 10.10.10.17
```

On the dhcp-master Pi (with the laptop on the LAN):

```
chronyc sources -v           # 10.10.10.17 selected (^*) with stratum < 10
hwclock --show               # coin-cell-backed RTC reports correct wall time
```

If `chronyc sources -v` on the Pi shows `10.10.10.17` at stratum 16 or
`^?` (unreachable), the laptop is up but lacks a real upstream — the
Pi falls back to `local stratum 10` against its own (ideally
coin-cell-backed) RTC. That's the intended fallback, not a bug.

If `chronyc clients` on the laptop stays empty after a Pi has booted,
something on the laptop is blocking UDP/123 inbound on the wired
interface — check `sudo ufw status` and `sudo nft list ruleset`.

That's it. Nothing else is required on the laptop for the field stack
to function — observing software, contract tests, and image-flashing
all run from the Pis or from a build host elsewhere.
