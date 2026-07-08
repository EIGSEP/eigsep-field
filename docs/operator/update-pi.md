# Updating a flashed Pi in place (pre-deployment)

`eigsep-field sync-image` brings an already-flashed Pi up to the state
of the checked-out `/opt/eigsep/src/eigsep-field` tree without pulling
the SD card. It is an ONLINE tool: run it before deployment, while the
Pi still has internet (GitHub, PyPI, apt mirrors). In the field, the
only mutation tools remain `eigsep-field patch/revert/capture`.

## One-time bootstrap

Deployed images may predate the command. Once per Pi:

    cd /opt/eigsep/src/eigsep-field && git pull
    sudo /opt/eigsep/venv/bin/pip install .
    sudo eigsep-field sync-image

## Routine use

    cd /opt/eigsep/src/eigsep-field && git pull
    sudo eigsep-field sync-image

The command self-updates from the tree and re-executes, then runs
these steps (see `--skip` / `--only` to cherry-pick):

| step      | what it does                                            |
|-----------|---------------------------------------------------------|
| apt       | installs the image's apt list (files/apt-packages.txt)  |
| wheelhouse| swaps /opt/eigsep/wheels to the blessed release artifact|
| files     | systemd units, /etc overlays, motd/CHEATSHEET, sudoers  |
| removals  | deletes tombstoned paths (removed-paths.txt)            |
| systemd   | daemon-reload + enable always-services                  |
| role      | re-applies hostname, static IP, chrony/redis, role units|
| sources   | clones new siblings, refreshes blessed-commit markers   |
| firmware  | refreshes blessed blobs (never flashes hardware)        |
| external  | installs missing vendor binaries (cmtvna)               |
| dirs      | ownership + symlinks                                    |
| verify    | runs `eigsep-field doctor`                              |

Preview everything first with:

    eigsep-field sync-image --dry-run

Notes:

- The wheelhouse step needs a published release for the tree's
  manifest `release`; on a mid-cycle tree it warns and skips — use
  `git pull` + `eigsep-field patch` in the sibling trees as usual.
- If the blessed Pico UF2 changed, flash it explicitly with
  `flash-picos` (or `eigsep-field revert pico-firmware`).
- The role step restarts redis-server; don't run mid-observation.
- Re-running is always safe: every step is idempotent.
- Whenever the venv gets reinstalled from the wheelhouse (a fresh
  swap, or recovery from a previous run whose pip install didn't
  land), restart services or reboot before deployment — check status
  first with `eigsep-field services list`.
