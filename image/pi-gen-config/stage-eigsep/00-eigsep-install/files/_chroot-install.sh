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
# build-essential + gcc-arm-none-eabi + cmake + libusb-1.0 are the
# cross-compile toolchain for in-field rebuilds of pico-firmware via
# `eigsep-field patch pico-firmware`. The pico-sdk submodule is
# pre-fetched alongside the pico-firmware clone (clone-sources reads
# recursive_submodules from the manifest) so build.sh runs offline on
# the Pi.
#
# The cmtvna line is the Qt 6 / GL runtime the proprietary cmtvna
# binary ([external.cmtvna]) needs. It ships a vendored Qt 6.10.2 with
# RUNPATH=$ORIGIN/../../lib, but its xcb platform plugin
# (plugins/platforms/libqxcb.so) and the libQt6XcbQpa chain pull in a
# pile of system libs that aren't in the vendored tree. The system
# packages fall in via the RUNPATH fall-through. Upstream's README
# assumes Trixie Desktop; this image is Lite, so none of this stack
# arrives transitively. Set derived from
# `ldd /opt/eigsep/cmt-vna/bin/cmtvna` plus
# `ldd /opt/eigsep/cmt-vna/plugins/platforms/libqxcb.so` on
# cmtvna 1.7.1.
apt-get install -y --no-install-recommends \
    python3 python3-venv python3-pip \
    redis-server \
    isc-dhcp-server \
    chrony \
    picotool \
    xvfb \
    libegl1 libopengl0 libfontconfig1 \
    libxkbcommon0 libxkbcommon-x11-0 \
    libxcb-cursor0 libxcb-icccm4 libxcb-keysyms1 libxcb-shape0 libxcb-xkb1 \
    git curl \
    vim-nox \
    build-essential pkg-config libusb-1.0-0-dev cmake \
    gcc-arm-none-eabi libstdc++-arm-none-eabi-newlib

# Overlay dhcp configs after apt-get install, not before in 00-run.sh:
# pre-existing conffiles in /etc trigger a dpkg prompt that fails under
# noninteractive apt. Same post-apt-overlay pattern as the redis include
# below.
install -m 0644 /opt/eigsep/dhcp/dhcpd.conf /etc/dhcp/dhcpd.conf
install -m 0644 /opt/eigsep/dhcp/isc-dhcp-server \
    /etc/default/isc-dhcp-server
rm -rf /opt/eigsep/dhcp

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
# requirements.txt already pins eigsep-field==<release> with --hash
# (appended by scripts/build-wheelhouse.sh step 4), so a single -r install
# resolves the meta wheel and every transitive dep. Passing `eigsep-field`
# as a bare positional here would be unpinned and reject the resolve under
# --require-hashes.
/opt/eigsep/venv/bin/pip install --no-index \
    --find-links /opt/eigsep/wheels \
    --require-hashes \
    -r /opt/eigsep/wheels/requirements.txt

# Hardware-only Python packages (e.g. casperfpga) declared in
# manifest.toml [hardware.*]. Mirrors install-field.sh:46-50. Required on
# field Pis whose service code paths import them — eigsep-observe on the
# backend lazy-imports casperfpga, so a missing wheel causes ImportError
# at first boot. Skipping when hardware-requirements.txt is absent keeps
# the image build resilient against wheelhouse builds that ran with no
# [hardware.*] entries.
if [ -f /opt/eigsep/wheels/hardware-requirements.txt ]; then
    /opt/eigsep/venv/bin/pip install --no-index \
        --find-links /opt/eigsep/wheels \
        --require-hashes \
        -r /opt/eigsep/wheels/hardware-requirements.txt
fi

ln -sf /opt/eigsep/venv/bin/eigsep-field /usr/local/bin/eigsep-field

# Do not start isc-dhcp-server at image build time — only the one Pi
# with `role = backend` in /boot/firmware/eigsep-role.conf should
# run it. eigsep-first-boot.service enables it on first boot via the
# manifest's [services.isc_dhcp] entry.
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

# Clone every [packages.*] / [hardware.*] tree into /opt/eigsep/src/<name>
# at the manifest-pinned tag. Operator-owned so `git checkout -b
# field-fix-XXX` works in the field. Needs network in the chroot, which
# we have here (apt-get update succeeded above). The eigsep-field
# self-clone is not part of this — 00-run.sh already staged it from the
# runner's checkout; we just chown to the operator user here, since
# `eigsep` doesn't exist on the runner.
install -d /opt/eigsep/src
/opt/eigsep/venv/bin/python -m eigsep_field._image_install clone-sources
if [ -d /opt/eigsep/src/eigsep-field ]; then
    chown -R eigsep:eigsep /opt/eigsep/src/eigsep-field
fi

# Field-capture output dir: operator-writable so `eigsep-field capture`
# doesn't need sudo.
install -d -m 0755 -o eigsep -g eigsep /opt/eigsep/captures

# Pre-create the [external.cmtvna] install path with operator ownership.
# The proprietary cmtvna binary cannot be redistributed under our MIT
# license, so the operator stages it once after first boot via
# `sudo install-cmtvna.sh`. We just guarantee the target dir exists
# with the right owner so the service unit's WorkingDirectory resolves
# even before the binary lands. Doctor flags the missing binary on
# panda role until the operator runs the install step.
install -d -m 0755 -o eigsep -g eigsep /opt/eigsep/cmt-vna
install -d -m 0755 -o eigsep -g eigsep /opt/eigsep/cmt-vna/bin

# Operator navigation aids in /home/eigsep. Canonical paths stay under
# /opt/eigsep (FHS, user-account-agnostic for systemd units, stable for
# `eigsep-field patch`); the homedir gets symlinks so `ls ~`, `cd ~/src`,
# and `cat ~/CHEATSHEET.md` work as expected without the operator
# having to remember /opt/eigsep/. The symlinks resolve to existing
# targets (captures dir was just created above; CHEATSHEET.md was
# staged by 00-run.sh before the chroot install).
ln -sfn /opt/eigsep/src           /home/eigsep/src
ln -sfn /opt/eigsep/captures      /home/eigsep/captures
ln -sfn /opt/eigsep/CHEATSHEET.md /home/eigsep/CHEATSHEET.md
chown -h eigsep:eigsep \
    /home/eigsep/src \
    /home/eigsep/captures \
    /home/eigsep/CHEATSHEET.md
