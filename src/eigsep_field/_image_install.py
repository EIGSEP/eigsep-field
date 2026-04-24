"""Image-build helper invoked by ``stage-eigsep/00-run.sh`` inside the
pi-gen chroot.

The stage's bash ``install`` commands handle the file copy from
``files/systemd/`` into ``${ROOTFS_DIR}/etc/systemd/system/`` (no manifest
needed — the directory is the file-copy source of truth). This helper
consumes the manifest and runs ``systemctl enable`` on every service with
``activation = "always"``. Role services are left disabled; they're
enabled on first boot by ``eigsep-first-boot.service``.
"""

from __future__ import annotations

import argparse
import sys

from eigsep_field import load_manifest
from eigsep_field._services import systemctl


def _cmd_enable_always(_: argparse.Namespace) -> int:
    services = load_manifest().get("services", {})
    failed = 0
    enabled = 0
    for name, entry in services.items():
        if entry.get("activation") != "always":
            continue
        unit = entry["unit"]
        rc, msg = systemctl("enable", unit)
        if rc == 0:
            enabled += 1
            print(f"  enabled {unit} ({name})")
        else:
            failed += 1
            print(f"  FAIL enable {unit} ({name}): {msg}", file=sys.stderr)
    print(f"enabled {enabled} always-services; {failed} failed")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="eigsep_field._image_install")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser(
        "enable-always",
        help="systemctl enable every activation=always service",
    ).set_defaults(func=_cmd_enable_always)
    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
