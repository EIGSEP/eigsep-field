"""Image-build helper invoked by ``stage-eigsep/00-eigsep-install/00-run.sh``
inside the pi-gen chroot.

The stage's bash ``install`` commands handle the file copy from
``files/systemd/`` into ``${ROOTFS_DIR}/etc/systemd/system/`` (no manifest
needed — the directory is the file-copy source of truth). This helper
consumes the manifest and:

- ``enable-always``: ``systemctl enable`` every service with
  ``activation = "always"``. Role services are left disabled; they're
  enabled on first boot by ``eigsep-first-boot.service``.
- ``clone-sources``: ``git clone`` every ``[packages.*]`` and
  ``[hardware.*]`` (plus eigsep-field itself) into
  ``/opt/eigsep/src/<name>/`` at the manifest-pinned tag, freezing the
  resolved commit in ``.eigsep-blessed-commit`` so the doctor's drift
  check is deterministic and offline. Operator-owned so ``git commit``
  works in the field.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from eigsep_field import load_manifest
from eigsep_field._services import systemctl

EIGSEP_FIELD_URL = "https://github.com/EIGSEP/eigsep-field"


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


def _clone_targets(manifest: dict) -> list[tuple[str, str, str]]:
    """Return (name, source, tag) for every tree to clone into /opt/eigsep/src.

    Order matters for readable build logs: packages first, then hardware,
    then the eigsep-field self-clone last (so its absence in earlier
    iterations isn't load-bearing for any sibling).
    """
    targets: list[tuple[str, str, str]] = []
    for name, entry in manifest.get("packages", {}).items():
        targets.append((name, entry["source"], entry["tag"]))
    for name, entry in manifest.get("hardware", {}).items():
        targets.append((name, entry["source"], entry["tag"]))
    image_tag = manifest.get("image", {}).get("tag")
    eigsep_tag = image_tag or f"v{manifest['release']}"
    targets.append(("eigsep-field", EIGSEP_FIELD_URL, eigsep_tag))
    return targets


def _cmd_clone_sources(args: argparse.Namespace) -> int:
    manifest = load_manifest()
    src_root = Path(args.src_root)
    src_root.mkdir(parents=True, exist_ok=True)

    targets = _clone_targets(manifest)
    failed = 0
    for name, source, tag in targets:
        dest = src_root / name
        if dest.exists():
            print(f"  skip {name}: {dest} already present")
            continue
        print(f"  cloning {name} ({tag}) -> {dest}")
        rc = subprocess.run(
            ["git", "clone", "--branch", tag, source, str(dest)]
        ).returncode
        if rc != 0:
            failed += 1
            print(f"  FAIL clone {name}", file=sys.stderr)
            continue
        head_proc = subprocess.run(
            ["git", "-C", str(dest), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
        )
        if head_proc.returncode != 0:
            failed += 1
            print(f"  FAIL resolve HEAD for {name}", file=sys.stderr)
            continue
        head = head_proc.stdout.strip()
        (dest / ".eigsep-blessed-commit").write_text(head + "\n")
        # Hide the marker from `git status` so the operator's working
        # tree looks clean post-clone. Repo-local exclude (not
        # .gitignore) so a future `git pull` of upstream can't ever
        # remove it.
        exclude = dest / ".git" / "info" / "exclude"
        if exclude.exists():
            with exclude.open("a") as f:
                f.write(".eigsep-blessed-commit\n")
        subprocess.run(
            ["chown", "-R", f"{args.user}:{args.user}", str(dest)],
            check=False,
        )
    print(f"cloned {len(targets) - failed} sibling(s); {failed} failed")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="eigsep_field._image_install")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser(
        "enable-always",
        help="systemctl enable every activation=always service",
    ).set_defaults(func=_cmd_enable_always)

    cs = sub.add_parser(
        "clone-sources",
        help="git clone packages + hardware + eigsep-field into "
        "/opt/eigsep/src/",
    )
    cs.add_argument(
        "--src-root",
        default="/opt/eigsep/src",
        help="destination root (default /opt/eigsep/src)",
    )
    cs.add_argument(
        "--user",
        default="eigsep",
        help="operator user that should own the trees (default eigsep)",
    )
    cs.set_defaults(func=_cmd_clone_sources)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
