# Operator laptop capabilities

The Pi image is self-sufficient: with no laptop attached, the Pis come
up, the dhcp-master serves DHCP and runs `chrony` with `local stratum
10`, and the cluster mutually agrees on time. The laptop is a
convenience for the operator, not a dependency for the system.

What the laptop needs for full ops:

- **Wired Ethernet on the EIGSEP LAN.** The dhcp-master Pi serves
  `10.10.10.0/24` on eth0; the laptop pulls a DHCP lease from the
  dynamic range (`10.10.10.12`–`10.10.10.255`).
- **SSH client.** Reaching the Pis at `10.10.10.1` (dhcp-master) and
  the static reservations in
  [`image/pi-gen-config/stage-eigsep/files/dhcp/dhcpd.conf`](../../image/pi-gen-config/stage-eigsep/files/dhcp/dhcpd.conf).
- **(Optional) chrony serving NTP.** Reserve `10.10.10.2` for the
  laptop in `dhcpd.conf` and run chrony with `allow 10.10.10.0/24`.
  This upgrades the cluster from "self-agreed" to "true UTC" while
  the laptop is connected. Without it, the dhcp-master falls back to
  `local stratum 10` and the cluster keeps mutually agreed time, just
  not pinned to UTC.

That's it. Nothing else is required on the laptop for the field stack
to function — observing software, contract tests, and image-flashing
all run from the Pis or from a build host elsewhere.
