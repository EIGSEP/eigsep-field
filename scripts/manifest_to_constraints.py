"""Emit a pip constraints file from manifest.toml.

Used by build-wheelhouse.sh to pass `--constraint` during resolution.
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path


def main(argv: list[str]) -> int:
    manifest_path = Path(argv[1]) if len(argv) > 1 else Path("manifest.toml")
    manifest = tomllib.loads(manifest_path.read_text())
    for entry in manifest["packages"].values():
        print(f"{entry['pypi']}=={entry['version']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
