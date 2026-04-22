"""CI guard: every version in manifest.toml must exist upstream.

For each [packages.X], confirm the pinned version is published on PyPI.
For each [firmware.X], confirm the tag or commit exists on GitHub.

Fails non-zero if anything is unreachable. Run in validate.yml.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tomllib
import urllib.error
import urllib.request
from pathlib import Path


def pypi_has(name: str, version: str) -> bool:
    url = f"https://pypi.org/pypi/{name}/{version}/json"
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            return r.status == 200
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False
        raise


def gh_has_tag(repo_url: str, tag: str) -> bool:
    owner_repo = repo_url.rstrip("/").removeprefix("https://github.com/")
    token = os.environ.get("GITHUB_TOKEN", "")
    cmd = ["gh", "api", f"/repos/{owner_repo}/git/refs/tags/{tag}"]
    env = {**os.environ, "GH_TOKEN": token} if token else os.environ
    r = subprocess.run(cmd, capture_output=True, env=env)
    return r.returncode == 0


def gh_has_commit(repo_url: str, sha: str) -> bool:
    owner_repo = repo_url.rstrip("/").removeprefix("https://github.com/")
    cmd = ["gh", "api", f"/repos/{owner_repo}/commits/{sha}"]
    r = subprocess.run(cmd, capture_output=True)
    return r.returncode == 0


def main(argv: list[str]) -> int:
    manifest_path = Path(argv[1]) if len(argv) > 1 else Path("manifest.toml")
    manifest = tomllib.loads(manifest_path.read_text())
    errors: list[str] = []

    for key, entry in manifest["packages"].items():
        name = entry["pypi"]
        version = entry["version"]
        if not pypi_has(name, version):
            errors.append(f"PyPI missing: {name}=={version}")

    for key, entry in manifest.get("hardware", {}).items():
        tag = entry.get("tag", "")
        if not tag:
            # Placeholder entry on a draft PR anticipating a sibling
            # release (e.g. eigsep_dac before its first tag). Warn, don't
            # fail — refresh-lock.sh still requires a real tag, so the
            # release cannot actually ship without one.
            print(
                f"warning: {key}: empty tag (draft placeholder); skipping",
                file=sys.stderr,
            )
            continue
        if not gh_has_tag(entry["source"], tag):
            errors.append(f"GH tag missing: {entry['source']} @ {tag}")

    for key, entry in manifest.get("firmware", {}).items():
        if entry.get("tag"):
            if not gh_has_tag(entry["source"], entry["tag"]):
                errors.append(
                    f"GH tag missing: {entry['source']} @ {entry['tag']}"
                )
        elif entry.get("commit"):
            if not gh_has_commit(entry["source"], entry["commit"]):
                errors.append(
                    f"GH commit missing: {entry['source']} @ {entry['commit']}"
                )

    if errors:
        print("manifest verification failed:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1

    n_hw = len(manifest.get("hardware", {}))
    hw_tail = f" + {n_hw} hardware tag(s)" if n_hw else ""
    print(
        f"manifest OK: {len(manifest['packages'])} packages verified on PyPI"
        f"{hw_tail}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
