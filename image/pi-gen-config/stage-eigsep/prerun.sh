#!/bin/bash -e
# pi-gen stage prerun: copies the previous stage's rootfs into this stage.
if [ ! -d "${ROOTFS_DIR}" ]; then
    copy_previous
fi
