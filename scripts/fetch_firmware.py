"""Download firmware blobs named in manifest.toml into a destination tree.

Called by .github/workflows/image.yml to stage the Pico .uf2 and RFSoC
.npz into pi-gen's files/ before building the image. Verifies sha256 if
populated in the manifest.

By default unresolvable entries (no ``tag`` set, or download produces no
file) warn-and-continue so DEV image builds (workflow_dispatch on a SHA
where a sibling firmware repo hasn't tagged yet) still produce an image.
The operator scp's the missing blob onto the test Pi before exercising
the dependent service. Pass ``--strict`` for release builds to restore
fail-fast: a blessed image must never ship with a firmware blob missing.
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
import tomllib
from pathlib import Path


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _gh_download(repo_url: str, tag: str, asset: str, dest: Path) -> None:
    owner_repo = repo_url.rstrip("/").removeprefix("https://github.com/")
    dest.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "gh",
            "release",
            "download",
            tag,
            "--repo",
            owner_repo,
            "--pattern",
            asset,
            "--dir",
            str(dest),
        ],
        check=True,
    )


def _unresolved(kind: str, reason: str, *, strict: bool) -> int:
    # Strict: fail-fast so a release build never ships an image with a
    # firmware blob missing. Lenient: warn loudly so DEV builds complete
    # (operator delivers the blob out-of-band on the test Pi).
    severity = "error" if strict else "warning"
    print(
        f"{kind}: {severity}: {reason}. "
        f"Populate the tag in manifest.toml (or remove the entry if the "
        f"asset is intentionally absent). DEV builds proceed without it; "
        f"release builds (--strict) fail here.",
        file=sys.stderr,
    )
    return 1 if strict else 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest")
    parser.add_argument("out_root")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail-fast on unresolvable entries (release builds).",
    )
    ns = parser.parse_args(argv[1:])

    manifest_path = Path(ns.manifest)
    out_root = Path(ns.out_root)
    manifest = tomllib.loads(manifest_path.read_text())

    rc = 0
    for kind, entry in manifest.get("firmware", {}).items():
        asset = entry["asset"]
        dest_dir = out_root / kind
        tag = entry.get("tag")
        if not tag:
            step = _unresolved(
                kind,
                f"cannot resolve [firmware.{kind}] — no 'tag' set",
                strict=ns.strict,
            )
            rc = rc or step
            continue
        _gh_download(entry["source"], tag, asset, dest_dir)

        path = dest_dir / asset
        if not path.exists():
            step = _unresolved(
                kind,
                f"download succeeded but {path} missing",
                strict=ns.strict,
            )
            rc = rc or step
            continue

        expected = entry.get("sha256", "")
        if expected:
            actual = _sha256(path)
            if actual != expected:
                print(
                    f"{kind}: sha256 mismatch "
                    f"(expected {expected[:12]}…, got {actual[:12]}…)",
                    file=sys.stderr,
                )
                return 1
            print(f"{kind}: {asset} sha256 verified")
        else:
            print(f"{kind}: {asset} downloaded (no sha256 pinned)")

    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv))
