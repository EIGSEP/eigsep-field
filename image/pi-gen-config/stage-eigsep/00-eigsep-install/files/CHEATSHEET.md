# EIGSEP field cheatsheet — release {{release}}
{{dev_banner}}
The Pi is offline. No `pip install <X>`, no `git pull`, no `apt update`.
Everything you need is already on disk.

## Locations

    /opt/eigsep/venv         Python env (already on PATH after login)
    /opt/eigsep/src/<name>   Editable sibling source trees
    /opt/eigsep/wheels       Offline wheel cache + requirements.txt
    /opt/eigsep/src/eigsep-field/uv.lock     Blessed lockfile
    /etc/eigsep/manifest.toml                 Blessed version tuple
    /opt/eigsep/captures/    Field diffs you've captured

Homedir shortcuts (symlinks into /opt/eigsep):

    ~/src           -> /opt/eigsep/src
    ~/captures      -> /opt/eigsep/captures
    ~/CHEATSHEET.md -> /opt/eigsep/CHEATSHEET.md

## Daily

    eigsep-field info                    blessed vs installed
    eigsep-field doctor                  role + firmware + services + drift
    eigsep-field services list           service state for this Pi's role
    systemctl status <unit>              one service detail
    journalctl -u <unit> -f              tail logs

## Run a script by hand

    cd $(eigsep-field src eigsep_observing)
    python scripts/panda_observe.py      # runs in /opt/eigsep/venv
    python scripts/live_status.py

## Hot-patch (sibling has a bug; you have a fix)

    cd $(eigsep-field src eigsep_observing)
    git checkout -b field-fix-NNN
    # edit, save
    git commit -am "field fix: <one-liner>"
    sudo eigsep-field patch eigsep_observing       # editable install + restart
    # verify the fix actually works

## Revert (the patch was wrong)

    sudo eigsep-field revert eigsep_observing      # one sibling
    sudo eigsep-field revert --all                 # everything back to blessed

## Capture (send the fix back to base)

    eigsep-field capture eigsep_observing
    # writes /opt/eigsep/captures/<sibling>-<timestamp>.patch
    # scp the .patch out via the ground laptop, open a PR upstream

## Danger

If `eigsep-field patch` says deps are missing: don't try to install them.
Run `sudo eigsep-field revert --all` and call it in.

If a service won't start after revert:

    journalctl -u <unit> -e -n 200

Capture the output. systemd state is not in the patch flow.

`git pull` will fail (offline). To bring in upstream changes, sneakernet
a git bundle from a connected machine and `git fetch <bundle>`.
