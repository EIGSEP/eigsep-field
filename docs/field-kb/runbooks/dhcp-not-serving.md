# Runbook: DHCP not serving (LAN nodes get no address)

**Where:** backend Pi (the LAN's DHCP server).

## Symptom
SNAP / panda Pi / other LAN nodes don't get an IP, or can't reach the
backend at `10.10.10.10`.

## Likely causes
- `isc-dhcp-server.service` not running on the backend.
- `eth0` not at `10.10.10.10/24` (role not applied).
- Cabling / switch power.

## Diagnosis
On the backend Pi:

    systemctl status isc-dhcp-server.service
    journalctl -u isc-dhcp-server.service -n 100 --no-pager
    ip addr show eth0                 # expect inet 10.10.10.10/24
    cat /boot/firmware/eigsep-role.conf   # expect role = backend
    cat /var/lib/dhcp/dhcpd.leases | tail

## Fix
- If the role line is wrong: set `role = backend`, then re-apply the
  role. `eigsep-first-boot.service` self-disables after its first run, so
  a `restart` will NOT re-apply it. Re-enable it and reboot:
  `sudo systemctl enable eigsep-first-boot.service` then `sudo reboot`.
  That re-applies the static IP and enables the role services.
- If the service is down: `sudo systemctl restart isc-dhcp-server.service`.
- If `eth0` has no/!wrong address: re-apply the role as above; confirm
  the cable is in the correct port and the switch is powered.
