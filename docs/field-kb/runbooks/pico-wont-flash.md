# Runbook: Pico won't flash

**Where:** panda Pi (the host that flashes the Pico over USB).

## Symptom
`eigsep-field patch pico-firmware` fails, or the Pico is not detected.

## Likely causes
- Pico not in BOOTSEL/USB mass-storage mode, or USB cable is power-only.
- `picomanager.service` holding the serial port.
- Build toolchain or `picotool` issue.

## Diagnosis
On the panda Pi:

    lsusb | grep -i 'Raspberry\|2e8a'   # 2e8a = Raspberry Pi vendor id
    picotool info                        # expect device info
    systemctl status picomanager.service

## Fix
- Stop the host so it releases the device, then flash:
  `sudo systemctl stop picomanager.service`, then
  `eigsep-field patch pico-firmware` (builds + flashes the UF2), then
  `sudo systemctl start picomanager.service`.
- If `picotool` can't see the Pico: replug with a known data USB cable;
  if needed put the Pico in BOOTSEL mode (hold BOOTSEL while plugging).
- To return to the blessed firmware: `eigsep-field revert pico-firmware`
  (deletes the patch drop-in and reflashes the blessed UF2).
