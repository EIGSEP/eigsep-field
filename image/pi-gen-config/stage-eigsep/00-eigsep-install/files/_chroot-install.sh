#!/bin/bash
# Runs inside the stage-eigsep chroot. Staged at /opt/eigsep/_chroot-install.sh
# by ../00-run.sh (host side) and removed after on_chroot returns.
#
# This lives in a file (and is invoked as `on_chroot /opt/eigsep/_chroot-install.sh`)
# rather than as a heredoc piped to on_chroot's stdin so that dpkg postinst
# scripts run during apt-get install can't drain bash's command stream and
# silently truncate the rest of the script. With a heredoc, the inner bash
# reads commands from stdin; any postinst that reads stdin (chrony,
# isc-dhcp-server, etc.) consumes bytes, and after apt-get returns bash hits
# EOF and exits 0 -- pi-gen sees success but the venv install never ran. See
# the v2026.5.0-rc cycle in git history for the diagnosis.
set -euo pipefail

apt-get update
apt-get install -y --no-install-recommends \
    python3 python3-venv python3-pip \
    redis-server \
    isc-dhcp-server \
    chrony \
    picotool \
    xvfb \
    git curl

# Pull our overrides into the Debian-shipped redis.conf. Appended at the
# end so the directives in eigsep.conf override the stock loopback-only
# bind and protected-mode yes. The snippet itself was staged into the
# rootfs by 00-run.sh, before this script ran.
if ! grep -qF "redis.conf.d/eigsep.conf" /etc/redis/redis.conf; then
    {
        echo ""
        echo "# EIGSEP field overrides — see /etc/redis/redis.conf.d/eigsep.conf"
        echo "include /etc/redis/redis.conf.d/eigsep.conf"
    } >> /etc/redis/redis.conf
fi

python3 -m venv /opt/eigsep/venv
/opt/eigsep/venv/bin/pip install --no-index \
    --find-links /opt/eigsep/wheels \
    --require-hashes \
    -r /opt/eigsep/wheels/requirements.txt \
    eigsep-field

ln -sf /opt/eigsep/venv/bin/eigsep-field /usr/local/bin/eigsep-field

# Do not start isc-dhcp-server at image build time — only the one Pi
# that's given `dhcp = true` in /boot/eigsep-role.conf should run it.
systemctl disable isc-dhcp-server.service || true

# Mask systemd-timesyncd so it can't fight chrony for the clock. The
# chrony postinst usually masks it, but we mask explicitly to be robust
# against pi-gen base image changes.
systemctl disable systemd-timesyncd.service || true
systemctl mask systemd-timesyncd.service || true

# Enable every activation="always" service from manifest.toml.
# Role-scoped services are installed but left disabled; first boot's
# eigsep-first-boot.service enables the matching subset.
/opt/eigsep/venv/bin/python -m eigsep_field._image_install enable-always

# Clone every [packages.*] / [hardware.*] tree (plus eigsep-field) into
# /opt/eigsep/src/<name> at the manifest-pinned tag. Operator-owned so
# `git checkout -b field-fix-XXX` works in the field. Needs network in
# the chroot, which we have here (apt-get update succeeded above).
install -d /opt/eigsep/src
/opt/eigsep/venv/bin/python -m eigsep_field._image_install clone-sources

# Field-capture output dir: operator-writable so `eigsep-field capture`
# doesn't need sudo.
install -d -m 0755 -o eigsep -g eigsep /opt/eigsep/captures
