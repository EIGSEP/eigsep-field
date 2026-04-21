#!/bin/bash -e
# Stage runs in chroot. Installs system packages, drops the offline
# wheelhouse, installs the eigsep-field meta-package, and enables
# systemd units.
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

on_chroot << 'EOF'
set -e
apt-get update
apt-get install -y --no-install-recommends \
    python3 python3-venv python3-pip \
    redis-server \
    picotool \
    git curl

python3 -m venv /opt/eigsep/venv
/opt/eigsep/venv/bin/pip install --no-index \
    --find-links /opt/eigsep/wheels \
    --require-hashes \
    -r /opt/eigsep/wheels/requirements.txt \
    eigsep-field

ln -sf /opt/eigsep/venv/bin/eigsep-field /usr/local/bin/eigsep-field
EOF

install -m 0644 files/systemd/eigsep-panda.service    "${ROOTFS_DIR}/etc/systemd/system/eigsep-panda.service"
install -m 0644 files/systemd/eigsep-observer.service "${ROOTFS_DIR}/etc/systemd/system/eigsep-observer.service"
install -m 0644 files/systemd/eigsep.target           "${ROOTFS_DIR}/etc/systemd/system/eigsep.target"

on_chroot << 'EOF'
systemctl enable redis-server.service
systemctl enable eigsep-panda.service || true
systemctl enable eigsep-observer.service || true
systemctl enable eigsep.target
EOF
