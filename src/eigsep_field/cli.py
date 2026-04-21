"""eigsep-field CLI: info / verify / doctor.

Intentionally does **not** import sibling packages at module import time.
``doctor`` must run even when the stack is broken.
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from eigsep_field import load_manifest


def _versions_equal(a: str, b: str) -> bool:
    """Compare versions through PEP 440 normalization (e.g. 04 == 4)."""
    try:
        from packaging.version import Version

        return Version(a) == Version(b)
    except Exception:
        return a == b


def _cmd_info(_: argparse.Namespace) -> int:
    manifest = load_manifest()
    print(f"release: {manifest['release']}  python: {manifest['python']}")
    print()
    print(f"{'package':<24} {'blessed':<12} {'installed':<12} status")
    print("-" * 60)
    any_drift = False
    for entry in manifest["packages"].values():
        name = entry["pypi"]
        blessed = entry["version"]
        try:
            installed = version(name)
        except PackageNotFoundError:
            installed = "(not installed)"
            status = "MISSING"
        else:
            status = "ok" if _versions_equal(installed, blessed) else "DRIFT"
        if status != "ok":
            any_drift = True
        print(f"{name:<24} {blessed:<12} {installed:<12} {status}")
    return 1 if any_drift else 0


def _cmd_verify(_: argparse.Namespace) -> int:
    """Run eigsep_observing's producer-contract tests if available."""
    try:
        import eigsep_observing  # noqa: F401
    except ImportError:
        print(
            "eigsep_observing not installed; skipping verify", file=sys.stderr
        )
        return 1

    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "--no-header",
        "--pyargs",
        "eigsep_observing.tests.test_producer_contracts",
    ]
    r = subprocess.run(cmd)
    if r.returncode != 0:
        cmd_fallback = [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "--no-header",
            str(_find_observing_tests() / "test_producer_contracts.py"),
        ]
        r = subprocess.run(cmd_fallback)
    return r.returncode


def _find_observing_tests() -> Path:
    import eigsep_observing

    pkg_root = Path(eigsep_observing.__file__).resolve().parent.parent.parent
    tests = pkg_root / "tests"
    if tests.exists():
        return tests
    raise FileNotFoundError(
        "could not locate eigsep_observing tests; clone the repo "
        "at its manifest tag for `eigsep-field verify`"
    )


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _cmd_doctor(_: argparse.Namespace) -> int:
    manifest = load_manifest()
    problems: list[str] = []
    ok: list[str] = []

    # redis-server running?
    r = subprocess.run(
        ["systemctl", "is-active", "--quiet", "redis-server"],
        capture_output=True,
    )
    if r.returncode == 0:
        ok.append("redis-server active")
    else:
        problems.append("redis-server not active (systemctl is-active failed)")

    # firmware blobs present at expected paths with matching sha256?
    firmware_root = Path("/opt/eigsep/firmware")
    for kind, entry in manifest.get("firmware", {}).items():
        asset = firmware_root / kind / entry["asset"]
        if not asset.exists():
            problems.append(f"{kind}: missing {asset}")
            continue
        expected = entry.get("sha256", "")
        if not expected:
            ok.append(f"{kind}: {asset.name} present (no sha256 pinned)")
            continue
        actual = _sha256(asset)
        if actual != expected:
            problems.append(
                f"{kind}: sha256 mismatch for {asset.name} "
                f"(expected {expected[:12]}…, got {actual[:12]}…)"
            )
        else:
            ok.append(f"{kind}: {asset.name} sha256 matches")

    # every blessed python package installed at the blessed version?
    for entry in manifest["packages"].values():
        name = entry["pypi"]
        blessed = entry["version"]
        try:
            installed = version(name)
        except PackageNotFoundError:
            problems.append(f"{name}: not installed (blessed {blessed})")
            continue
        if not _versions_equal(installed, blessed):
            problems.append(
                f"{name}: installed {installed}, blessed {blessed}"
            )
        else:
            ok.append(f"{name}: {installed}")

    for line in ok:
        print(f"  ok   {line}")
    for line in problems:
        print(f"  FAIL {line}", file=sys.stderr)
    return 1 if problems else 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="eigsep-field")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser(
        "info", help="print installed vs blessed stack"
    ).set_defaults(func=_cmd_info)
    sub.add_parser(
        "verify", help="run eigsep_observing producer-contract tests"
    ).set_defaults(func=_cmd_verify)
    sub.add_parser(
        "doctor", help="check redis, firmware, installed stack"
    ).set_defaults(func=_cmd_doctor)
    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
