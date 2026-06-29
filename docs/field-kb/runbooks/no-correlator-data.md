# Runbook: no correlator data

**Where:** backend Pi (SNAP).

## Symptom
The observing stack reports no visibilities, or `eigsep-observe` logs
read errors from the SNAP.

## Likely causes
- `eigsep-observe.service` or `eigsep-observe-writer.service` not running.
- `redis-server` down (the buses are unavailable).
- `casperfpga` missing/broken, or the SNAP not reachable on the LAN.
- The SNAP bitstream not programmed.

## Diagnosis
Run on the backend Pi:

    systemctl status eigsep-observe.service eigsep-observe-writer.service
    journalctl -u eigsep-observe.service -n 100 --no-pager
    systemctl status redis-server.service
    redis-cli ping            # expect: PONG
    ip addr show eth0         # expect inet 10.10.10.10/24
    eigsep-field doctor

`eigsep-field doctor` is role-aware and will flag a missing `casperfpga`
or firmware blob on the backend.

## Fix
- Restart the observing services:
  `sudo systemctl restart eigsep-observe.service eigsep-observe-writer.service`.
- If `redis-cli ping` fails: `sudo systemctl restart redis-server.service`.
- If `doctor` reports `casperfpga` missing: the image is mis-built;
  reinstall hardware wheels from the wheelhouse (see
  `docs/operator/new-pi.md`).
- If the SNAP is unreachable: check the SNAP's power and Ethernet, and
  that it pulled a DHCP lease (see the DHCP runbook).
