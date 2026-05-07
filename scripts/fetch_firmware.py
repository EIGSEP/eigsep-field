"""Download firmware blobs named in manifest.toml into a destination tree.

Called by .github/workflows/image.yml to stage the Pico .uf2 and RFSoC
.npz into pi-gen's files/ before building the image. Verifies sha256 if
populated in the manifest.
"""

from __future__ import annotations

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


def main(argv: list[str]) -> int:
    manifest_path = Path(argv[1])
    out_root = Path(argv[2])
    manifest = tomllib.loads(manifest_path.read_text())

    for kind, entry in manifest.get("firmware", {}).items():
        asset = entry["asset"]
        dest_dir = out_root / kind
        if tag := entry.get("tag"):
            _gh_download(entry["source"], tag, asset, dest_dir)
        else:
            # Hard fail rather than warn-and-continue. A missing tag means
            # the firmware blob will not land in the rootfs, and downstream
            # services that load it (RFSoC bitstream → eigsep-observe)
            # will only fail on the field Pi at runtime. Failing here
            # keeps the bug visible at build time.
            print(
                f"{kind}: cannot resolve [firmware.{kind}] — no 'tag' set "
                f"in manifest.toml. Populate the tag (or remove the entry "
                f"if the asset is intentionally absent from this build).",
                file=sys.stderr,
            )
            return 1

        path = dest_dir / asset
        if not path.exists():
            print(
                f"{kind}: download succeeded but {path} missing",
                file=sys.stderr,
            )
            return 1

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

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
