"""Drift guard: every [firmware.*] entry in the top-level manifest.toml
must match its mirror in ``firmware/<dir>/manifest.toml``.

The per-firmware directory carries its own manifest mirror so the
firmware artifact is immediately inspectable from inside that directory
(see ``firmware/<dir>/README.md``); the two files must stay in lockstep.
This script enforces it.

Mapping is by ``(source, asset)`` rather than directory name — the
top-level key is ``rfsoc_bitstream`` while the on-disk dir is ``rfsoc``,
and we don't want to bake that convention into the check. Both
directions must be unique.

Fails (exit 1) with a readable diff. CI runs this via the
``firmware-drift`` job in ``validate.yml``. Usage:

    python3 scripts/check_firmware_drift.py            # full check
    python3 scripts/check_firmware_drift.py --quiet    # exit code only
"""

from __future__ import annotations

import argparse
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = REPO_ROOT / "manifest.toml"
FIRMWARE_DIR = REPO_ROOT / "firmware"


def _load_local_mirrors() -> dict[Path, dict]:
    out: dict[Path, dict] = {}
    if not FIRMWARE_DIR.is_dir():
        return out
    for sub in sorted(FIRMWARE_DIR.iterdir()):
        local = sub / "manifest.toml"
        if not local.is_file():
            continue
        out[local] = tomllib.loads(local.read_text())
    return out


def _match(
    top: dict[str, dict], local: dict[Path, dict]
) -> tuple[dict[str, tuple[Path, dict]], list[str]]:
    """Resolve top-level [firmware.<key>] to firmware/<dir>/manifest.toml
    by ``(source, asset)``. Returns (matched, problems) where ``matched``
    maps top key to ``(local_path, local_data)`` and ``problems`` lists
    unmatched-from-either-side entries.
    """
    problems: list[str] = []
    matched: dict[str, tuple[Path, dict]] = {}
    claimed_by: dict[Path, str] = {}
    for top_key, top_data in top.items():
        sig = (top_data.get("source"), top_data.get("asset"))
        candidates = [
            (p, d)
            for p, d in local.items()
            if (d.get("source"), d.get("asset")) == sig
        ]
        if not candidates:
            problems.append(
                f"  [firmware.{top_key}]: no firmware/*/manifest.toml "
                f"matches (source={sig[0]!r}, asset={sig[1]!r})"
            )
            continue
        if len(candidates) > 1:
            paths = ", ".join(
                str(p.relative_to(REPO_ROOT)) for p, _ in candidates
            )
            problems.append(
                f"  [firmware.{top_key}]: matches multiple local "
                f"mirrors ({paths}); (source, asset) must be unique"
            )
            continue
        chosen_path, _ = candidates[0]
        prior = claimed_by.get(chosen_path)
        if prior is not None:
            rel = chosen_path.relative_to(REPO_ROOT)
            problems.append(
                f"  [firmware.{prior}] and [firmware.{top_key}] both "
                f"match {rel}; (source, asset) must be unique across "
                f"[firmware.*]"
            )
            continue
        matched[top_key] = candidates[0]
        claimed_by[chosen_path] = top_key

    for path in local:
        if path not in claimed_by:
            rel = path.relative_to(REPO_ROOT)
            problems.append(
                f"  {rel}: no matching [firmware.*] in top-level manifest.toml"
            )
    return matched, problems


def _diff(
    top_key: str, top_data: dict, local_path: Path, local_data: dict
) -> list[str]:
    rel = local_path.relative_to(REPO_ROOT)
    problems: list[str] = []
    for field in sorted(set(top_data) | set(local_data)):
        t = top_data.get(field, "<MISSING>")
        lo = local_data.get(field, "<MISSING>")
        if t != lo:
            problems.append(
                f"  [firmware.{top_key}] vs {rel}: {field!r} drifted\n"
                f"    top-level: {t!r}\n"
                f"    local    : {lo!r}"
            )
    return problems


def check(quiet: bool = False) -> int:
    manifest = tomllib.loads(MANIFEST_PATH.read_text())
    top = manifest.get("firmware", {})
    local = _load_local_mirrors()

    matched, problems = _match(top, local)
    for top_key, (path, data) in matched.items():
        problems.extend(_diff(top_key, top[top_key], path, data))

    if problems:
        if not quiet:
            print(
                f"firmware-drift: {len(problems)} issue(s) "
                f"({len(matched)} mirror(s) checked):",
                file=sys.stderr,
            )
            for p in problems:
                print(p, file=sys.stderr)
            print(
                "\nFix by editing whichever side is wrong. When bumping a "
                "pin, change manifest.toml AND firmware/<dir>/manifest.toml "
                "together.",
                file=sys.stderr,
            )
        return 1
    if not quiet:
        print(f"firmware-drift: {len(matched)} mirror(s) OK")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="check_firmware_drift", description=__doc__
    )
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args(argv)
    return check(quiet=args.quiet)


if __name__ == "__main__":
    sys.exit(main())
