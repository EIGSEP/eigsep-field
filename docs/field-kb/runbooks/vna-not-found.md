# Runbook: VNA not found

**Where:** panda Pi (CMT-VNA).

## Symptom
`cmtvna.service` fails to start, or calibration can't reach the VNA.

## Likely causes
- The CMT VNA binary is not installed at `/opt/eigsep/cmt-vna`.
- The VNA is not powered / not enumerated on USB.
- `cmtvna.service` crashed.

## Diagnosis
On the panda Pi:

    eigsep-field doctor               # checks the cmtvna install_path/binary
    ls -l /opt/eigsep/cmt-vna/bin/cmtvna
    lsusb                             # look for the VNA device
    systemctl status cmtvna.service
    journalctl -u cmtvna.service -n 100 --no-pager

## Fix
- If the binary is missing: install it with
  `scripts/install-cmtvna.sh <path-to-archive>` (the operator scp's the
  vendor archive to the Pi first — see `docs/operator/new-pi.md`).
- If the device isn't on USB: check VNA power and the USB cable.
- If the service crashed: `sudo systemctl restart cmtvna.service`.
