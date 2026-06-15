# Glossary

One anchored definition per term. Acronyms are spelled out so the agent
can answer questions that use either form.

## SNAP
Smart Network ADC Processor — the CASPER FPGA board on the
**backend** Pi that digitizes and correlates the antenna signals. The
backend reads correlator data off it via `casperfpga`.

## RFSoC
Radio Frequency System-on-Chip — a separate standalone signal-generation
system (not a Pi, does not run the eigsep image). The backend Pi pushes
it a bitstream `.npz` over the network.

## CMT-VNA
The Copper Mountain Technologies Vector Network Analyzer attached to the
**panda** Pi, driven by `cmtvna.service`. Used for calibration
measurements. The vendor binary is installed under `/opt/eigsep/cmt-vna`
(executable `bin/cmtvna`).

## Pico
The Raspberry Pi Pico microcontroller(s) on the **panda** Pi, connected
over USB, running the EIGSEP C firmware. Flashed from the panda Pi.

## picohost
The Python package (in the `pico-firmware` repo) that talks to the Pico
over USB from the panda Pi. `picomanager.service` and `panda_observe`
use it.

## picomanager
The systemd service on the panda Pi that supervises communication with
the Pico(s).

## panda
The Pi **role** that runs the Pico host and the CMT VNA
(`picomanager.service`, `cmtvna.service`). Set by `role = panda` in
`/boot/firmware/eigsep-role.conf`.

## backend
The Pi **role** that runs the observing stack, Redis, and the LAN's
DHCP/NTP. Reads the SNAP correlator. Pinned to `eth0 = 10.10.10.10/24`.
Set by `role = backend` in `/boot/firmware/eigsep-role.conf`.

## casperfpga
The Python driver for the SNAP board. Required on the **backend** Pi
(`[hardware.casperfpga] roles = ["backend"]`). Missing it on a real
backend is an image-build bug, not optional.

## correlator
The SNAP-based cross-correlation engine that produces the visibility
data the observing stack records.

## Redis buses
The named message buses (`metadata`, `status`, `heartbeat`, `config`)
that the observing stack uses for inter-process communication via
`redis-server` on the backend Pi. Each bus has one writer and many
readers by construction.

## eigsep-observe
The backend systemd service that runs the observing loop.

## eigsep-observe-writer
The backend systemd service that writes observed data to disk.

## panda_observe
The operator-launched (not systemd) entry point on the panda Pi that
drives the actuators via `picohost` and runs the observing loop.

## chrony
The NTP daemon. The backend Pi serves time to the LAN; field Pis
discipline their clocks against it (plus an RTC on the backend).

## RTC
Real-Time Clock — a coin-cell-backed clock on the backend Pi 5 so it
keeps time across power cycles without a network sync.

## DHCP
Dynamic Host Configuration Protocol. The backend Pi runs
`isc-dhcp-server` and hands out `10.10.10.0/24` addresses to the LAN.

## Valon
The Valon frequency synthesizer, driven by the `pyvalon` package; the
local-oscillator / clock source for the signal chain.

## manifest / blessed tuple
`manifest.toml` in `eigsep-field` — the `==`-pinned set of sibling
package versions for a deployment campaign. The image, wheelhouse, and
this corpus are all built from it.

## eigsep-field
The umbrella repo (this one). Owns the manifest, the image recipe, the
`eigsep-field` CLI (`info`, `doctor`, `services`, `patch`), and this KB.

## doctor
`eigsep-field doctor` — the on-Pi health check that verifies packages,
firmware blobs, services, and role config for the Pi's role.

## bitstream
The FPGA configuration loaded onto the SNAP/RFSoC. The RFSoC bitstream
ships as a `.npz` staged on the backend Pi.

## UF2
The flashable firmware image format for the Pico. The blessed UF2 lives
at `/opt/eigsep/firmware/pico/`.
