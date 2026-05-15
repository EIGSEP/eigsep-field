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
# /boot/firmware/eigsep-role.conf has role = backend (server) or not (client).
install -d "${ROOTFS_DIR}/etc/eigsep/chrony"
for conf in files/chrony/*.conf; do
    [ -f "$conf" ] || continue
    install -m 0644 "$conf" \
        "${ROOTFS_DIR}/etc/eigsep/chrony/$(basename "$conf")"
done

# Stage DHCP configs under /opt/eigsep, not /etc/dhcp/ and /etc/default/.
# A pre-existing conffile in /etc triggers a dpkg prompt during the
# chroot's apt-get install isc-dhcp-server, which fails under
# noninteractive apt with "end of file on stdin at conffile prompt".
# _chroot-install.sh copies these into place after apt returns. Inert
# on Pis without role = backend in /boot/firmware/eigsep-role.conf —
# isc-dhcp-server is role-scoped to backend.
install -d "${ROOTFS_DIR}/opt/eigsep/dhcp"
install -m 0644 files/dhcp/dhcpd.conf \
    "${ROOTFS_DIR}/opt/eigsep/dhcp/dhcpd.conf"
install -m 0644 files/dhcp/isc-dhcp-server \
    "${ROOTFS_DIR}/opt/eigsep/dhcp/isc-dhcp-server"

# Field-LAN Redis overrides. Pulled in by an include line appended to
# /etc/redis/redis.conf below; see the snippet's header for the
# rationale (cross-Pi access on a physically-isolated private LAN).
install -d "${ROOTFS_DIR}/etc/redis/redis.conf.d"
install -m 0644 files/redis/eigsep.conf \
    "${ROOTFS_DIR}/etc/redis/redis.conf.d/eigsep.conf"

# CMT VNA udev rules. Mirrors cmt_vna/scripts/install_vna_rules.sh at
# the manifest-pinned tag; without it the cmtvna binary picks the
# SN0916 mock device and returns all zeros on real hardware.
install -d "${ROOTFS_DIR}/etc/udev/rules.d"
install -m 0644 files/udev/usb-cmt-vna.rules \
    "${ROOTFS_DIR}/etc/udev/rules.d/usb-cmt-vna.rules"

# Raspberry Pi Pico udev rules. picotool / flash-picos need raw libusb
# access to send reboot-to-BOOTSEL to the CDC-mode device; without
# this rule the operator has to run flash-picos under sudo (issue #30).
install -m 0644 files/udev/usb-pico.rules \
    "${ROOTFS_DIR}/etc/udev/rules.d/usb-pico.rules"

# uv config: pin uv to the on-disk wheelhouse and forbid any network
# index lookups. eigsep-field revert calls `uv sync` against this.
install -m 0644 files/etc-eigsep/uv.toml \
    "${ROOTFS_DIR}/etc/eigsep/uv.toml"

# Operator shell environment: activate /opt/eigsep/venv on every login
# and point uv at it so `uv pip install -e` from a sibling source tree
# Just Works without per-project .venvs.
install -d "${ROOTFS_DIR}/etc/profile.d"
install -m 0644 files/etc-profile-d/eigsep.sh \
    "${ROOTFS_DIR}/etc/profile.d/eigsep.sh"

# Sudoers drop-in: the operator can `sudo eigsep-field patch|revert`
# without a password but only that binary.
install -d -m 0755 "${ROOTFS_DIR}/etc/sudoers.d"
install -m 0440 files/sudoers.d/eigsep-field \
    "${ROOTFS_DIR}/etc/sudoers.d/eigsep-field"

# Stage the eigsep-field source tree from the runner's checkout. image.yml
# does `git clone --no-local "$GITHUB_WORKSPACE" files/eigsep-field-src`
# before invoking pi-gen, so the tree here is the SHA that triggered the
# build with full git history + tags. Mirrors the per-target writeout that
# _image_install.clone-sources does for sibling repos: copy in, freeze
# HEAD into .eigsep-blessed-commit (consumed by the doctor's drift
# check), and exclude that marker from `git status` so the operator's
# tree looks clean. chown is deferred to _chroot-install.sh because the
# `eigsep` user does not exist on the runner.
install -d "${ROOTFS_DIR}/opt/eigsep/src"
cp -a files/eigsep-field-src "${ROOTFS_DIR}/opt/eigsep/src/eigsep-field"
git -C files/eigsep-field-src rev-parse HEAD \
    > "${ROOTFS_DIR}/opt/eigsep/src/eigsep-field/.eigsep-blessed-commit"
echo ".eigsep-blessed-commit" \
    >> "${ROOTFS_DIR}/opt/eigsep/src/eigsep-field/.git/info/exclude"

# Cheatsheet + MOTD. Substitute {{release}} and {{dev_banner}} from the
# staged manifest so the on-disk copies are self-describing for whoever
# ssh's in. {{dev_banner}} resolves to a "*** DEV BUILD <sha> ***" line
# on dispatch / non-blessed-tag builds (see image.yml's "Stamp DEV
# marker" step) and is removed entirely on blessed builds.
RELEASE_VERSION=$(python3 -c "import tomllib; print(tomllib.load(open('files/etc-eigsep/manifest.toml','rb'))['release'])")
DEV_BANNER=$(python3 - <<'PY'
import tomllib
m = tomllib.load(open('files/etc-eigsep/manifest.toml', 'rb'))
img = m.get('image', {})
if img.get('dev'):
    sha = img.get('sha', 'unknown')
    print(
        f"*** DEV BUILD {sha} — not a blessed release ***",
        end='',
    )
PY
)
install -m 0644 files/CHEATSHEET.md "${ROOTFS_DIR}/opt/eigsep/CHEATSHEET.md"
install -m 0644 files/etc-eigsep/motd "${ROOTFS_DIR}/etc/motd"
if [ -z "${DEV_BANNER}" ]; then
    sed -i "/{{dev_banner}}/d" \
        "${ROOTFS_DIR}/opt/eigsep/CHEATSHEET.md" \
        "${ROOTFS_DIR}/etc/motd"
else
    sed -i "s|{{dev_banner}}|${DEV_BANNER}|g" \
        "${ROOTFS_DIR}/opt/eigsep/CHEATSHEET.md" \
        "${ROOTFS_DIR}/etc/motd"
fi
sed -i "s|{{release}}|${RELEASE_VERSION}|g" \
    "${ROOTFS_DIR}/opt/eigsep/CHEATSHEET.md" \
    "${ROOTFS_DIR}/etc/motd"

# Stage the chroot installer at a stable rootfs path and run it as a file,
# rather than feeding multi-step commands to `on_chroot << EOF`. With a
# heredoc, on_chroot's inner bash reads commands from stdin; dpkg postinst
# scripts inherit that stdin, and any postinst that reads from it (chrony,
# isc-dhcp-server, etc.) drains the heredoc -- bash then hits EOF after
# apt-get returns and exits 0 silently, so the venv install never runs and
# pi-gen reports success. Invoking on_chroot with a path runs `bash -p -e
# /opt/eigsep/_chroot-install.sh`, which reads the script as a file and is
# immune to that drain.
#
# Stage under /opt/eigsep (already created above), NOT /tmp -- on_chroot's
# first call will mount tmpfs over the rootfs's /tmp and hide anything we
# placed there from the host side.
install -m 0755 files/_chroot-install.sh \
    "${ROOTFS_DIR}/opt/eigsep/_chroot-install.sh"
on_chroot /opt/eigsep/_chroot-install.sh
rm -f "${ROOTFS_DIR}/opt/eigsep/_chroot-install.sh"
