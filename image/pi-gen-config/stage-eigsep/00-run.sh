#!/bin/bash -e
# Stage runs in chroot. Installs system packages, drops the offline
# wheelhouse, installs the eigsep-field meta-package, stages systemd
# unit files, and enables the activation="always" services declared in
# manifest.toml's [services.*] table.
#
# Inputs expected under $ROOTFS_DIR/tmp/stage-eigsep-files/ (staged by
# the outer image.yml workflow before invoking pi-gen):
#   wheels/                offline wheelhouse + requirements.txt
#   firmware/pico/*.uf2    Pico firmware
#   firmware/rfsoc/*.npz   RFSoC bitstream
#   manifest.toml          blessed stack manifest

install -d "${ROOTFS_DIR}/opt/eigsep"
install -d "${ROOTFS_DIR}/opt/eigsep/firmware/pico"
install -d "${ROOTFS_DIR}/opt/eigsep/firmware/rfsoc"
install -d "${ROOTFS_DIR}/etc/eigsep"

# Stage inputs from the host-side files/ tree that pi-gen rsynced in.
rsync -a files/wheels/    "${ROOTFS_DIR}/opt/eigsep/wheels/"
rsync -a files/firmware/  "${ROOTFS_DIR}/opt/eigsep/firmware/"
install -m 0644 files/etc-eigsep/manifest.toml "${ROOTFS_DIR}/etc/eigsep/manifest.toml"

# All unit files in files/systemd/ land in /etc/systemd/system/. The
# set of files here is the source of truth for the file-copy step; the
# manifest decides which of them are enabled at build time vs. first boot.
install -d "${ROOTFS_DIR}/etc/systemd/system"
for unit in files/systemd/*.service files/systemd/*.target; do
    [ -f "$unit" ] || continue
    install -m 0644 "$unit" \
        "${ROOTFS_DIR}/etc/systemd/system/$(basename "$unit")"
done

# Stage chrony role snippets. eigsep-first-boot.service symlinks the
# correct one into /etc/chrony/conf.d/eigsep.conf based on whether
# /boot/eigsep-role.conf has dhcp = true (server) or not (client).
install -d "${ROOTFS_DIR}/etc/eigsep/chrony"
for conf in files/chrony/*.conf; do
    [ -f "$conf" ] || continue
    install -m 0644 "$conf" \
        "${ROOTFS_DIR}/etc/eigsep/chrony/$(basename "$conf")"
done

on_chroot << 'EOF'
set -e
apt-get update
apt-get install -y --no-install-recommends \
    python3 python3-venv python3-pip \
    redis-server \
    isc-dhcp-server \
    chrony \
    picotool \
    xvfb \
    git curl

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
EOF
