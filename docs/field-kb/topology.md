# Topology — what runs where

The field image is uniform across Pis. A Pi's job is set by its **role**
in `/boot/firmware/eigsep-role.conf` (`role = panda` or
`role = backend`), applied on first boot by `eigsep-first-boot.service`.
Role is decoupled from the hardware model.

## panda Pi

- **Runs:** `picomanager.service`, `cmtvna.service`.
- **Wired to:** the Raspberry Pi Pico(s) over USB, and the CMT VNA.
- **Owns:** flashing the Pico(s) — `eigsep-field patch pico-firmware`
  builds and flashes the UF2 from this Pi.
- The panda-side observing entry point, `panda_observe`, is launched by
  the operator (not a systemd service) and drives the actuators via the
  Pico firmware (`picohost`).

## backend Pi

- **Runs:** `eigsep-observe.service`, `eigsep-observe-writer.service`,
  `redis-server`, and the LAN's `isc-dhcp-server`.
- **Wired to:** the SNAP board; it reads correlator data from the SNAP
  via `casperfpga` (the SNAP driver — required on backend).
- **Is the LAN's DHCP and NTP server by definition.** The backend role
  pins `eth0` to **`10.10.10.10/24`**, enables `isc-dhcp-server`, and
  serves chrony time.

## RFSoC

- A **separate standalone system — not a Pi**, does not run the eigsep
  image. The backend Pi holds the RFSoC bitstream `.npz` at
  `/opt/eigsep/firmware/rfsoc/` and pushes it to the RFSoC over the
  network.

## The LAN

- Subnet `10.10.10.0/24`. Backend Pi at `10.10.10.10` serves DHCP/NTP to
  the other nodes. The field image ships with WiFi disabled.
