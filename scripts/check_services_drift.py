"""Drift guard: every [services.*] entry with kind="sibling" must match
its upstream unit file at the pinned tag on the semantic fields that
change behavior.

The image's copy of a sibling unit file is allowed to differ from upstream
on path-shaped fields (ExecStart paths, WorkingDirectory) because the
image uses ``/opt/eigsep/...`` while the sibling's dev layout uses
``%h/...`` or ``/home/eigsep/...``; ``[Install] WantedBy`` is also
rewritten from upstream's ``multi-user.target`` to the image's role
targets (``eigsep-panda.target``/``eigsep-backend.target``). What must
NOT drift: the argv[0] binary name, After/Wants/Requires/Before (startup
ordering), User/Group (security posture), and Restart/Type (reliability
contract).

Fails (exit 1) with a readable diff if upstream added or removed any of
those fields since our copy was taken. Usage:

    python3 scripts/check_services_drift.py            # full check
    python3 scripts/check_services_drift.py --quiet    # exit code only

CI runs this via the services-drift job in validate.yml.
"""

from __future__ import annotations

import argparse
import configparser
import io
import shlex
import subprocess
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = REPO_ROOT / "manifest.toml"
SYSTEMD_DIR = (
    REPO_ROOT
    / "image"
    / "pi-gen-config"
    / "stage-eigsep"
    / "00-eigsep-install"
    / "files"
    / "systemd"
)

# Importable without `pip install .` — the script is invoked directly
# from CI and dev shells. _services.py has no eigsep_field-internal deps.
sys.path.insert(0, str(REPO_ROOT / "src"))
from eigsep_field._services import peer_package_for_service  # noqa: E402

# Fields we track for drift. Intentionally excluded:
#   - Path-shaped fields (ExecStart full path, WorkingDirectory, Environment).
#     The image rewrites these to /opt/eigsep/...
#   - [Install] WantedBy. Upstream dev units target multi-user.target so
#     they're active in a dev clone. The image wraps role services in
#     role targets (eigsep-panda.target, eigsep-backend.target) and
#     rewrites WantedBy accordingly; that divergence is structural, not drift.
TRACKED: dict[str, tuple[str, ...]] = {
    "Unit": ("After", "Wants", "Requires", "Before"),
    "Service": ("User", "Group", "Restart", "Type"),
}


def _parse_unit(text: str) -> configparser.ConfigParser:
    cp = configparser.ConfigParser(strict=False, interpolation=None)
    cp.optionxform = str
    cp.read_file(io.StringIO(text))
    return cp


def _argv0_basename(exec_start: str | None) -> str | None:
    """ExecStart may be ``/abs/path/bin --flag`` or ``prog --flag``; return
    the program's basename. Returns None when ExecStart is missing."""
    if not exec_start:
        return None
    value = exec_start.lstrip("-+@!")
    try:
        parts = shlex.split(value)
    except ValueError:
        parts = value.split()
    if not parts:
        return None
    return parts[0].rsplit("/", 1)[-1]


def _canonicalize(unit_text: str) -> dict:
    cp = _parse_unit(unit_text)
    out: dict = {}
    for section, fields in TRACKED.items():
        sect: dict = {}
        if cp.has_section(section):
            for field in fields:
                if cp.has_option(section, field):
                    raw = cp.get(section, field)
                    tokens = sorted(raw.split())
                    sect[field] = tokens
        out[section] = sect
    if cp.has_section("Service") and cp.has_option("Service", "ExecStart"):
        out["Service"]["_argv0"] = _argv0_basename(
            cp.get("Service", "ExecStart")
        )
    return out


class FetchError(Exception):
    """Raised when the upstream unit file cannot be retrieved."""


def _gh_raw_contents(source: str, tag: str, source_path: str) -> str:
    """Fetch a file's raw content via ``gh api``.

    Uses the authenticated ``gh`` CLI so private sibling repos work in CI
    (where ``GH_TOKEN`` is set) and for devs who've run ``gh auth login``.
    Falls back to a clear error if ``gh`` is missing or auth fails.
    """
    owner_repo = source.rstrip("/").removeprefix("https://github.com/")
    endpoint = f"/repos/{owner_repo}/contents/{source_path}?ref={tag}"
    try:
        r = subprocess.run(
            [
                "gh",
                "api",
                "-H",
                "Accept: application/vnd.github.raw",
                endpoint,
            ],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as e:
        raise FetchError(
            "gh CLI not found; install it or set GH_TOKEN in env"
        ) from e
    if r.returncode != 0:
        raise FetchError(
            f"gh api {endpoint} failed (rc={r.returncode}): "
            f"{r.stderr.strip() or r.stdout.strip()}"
        )
    return r.stdout


def _diff_canonical(upstream: dict, local: dict, name: str) -> list[str]:
    problems: list[str] = []
    for section, fields in TRACKED.items():
        up_sect = upstream.get(section, {})
        lo_sect = local.get(section, {})
        for field in fields:
            up = up_sect.get(field)
            lo = lo_sect.get(field)
            if up != lo:
                problems.append(
                    f"  {name}: [{section}] {field} drifted\n"
                    f"    upstream: {up}\n"
                    f"    local   : {lo}"
                )
    up_argv0 = upstream.get("Service", {}).get("_argv0")
    lo_argv0 = local.get("Service", {}).get("_argv0")
    if up_argv0 != lo_argv0:
        problems.append(
            f"  {name}: [Service] ExecStart argv[0] basename drifted\n"
            f"    upstream: {up_argv0}\n"
            f"    local   : {lo_argv0}"
        )
    return problems


def _check_tag_alignment(manifest: dict, name: str, entry: dict) -> list[str]:
    peer = peer_package_for_service(manifest, entry)
    if peer is None:
        return [
            f"  {name}: source {entry.get('source')!r} matches no "
            f"[packages.*].source — cannot cross-check tag"
        ]
    peer_name, peer_entry = peer
    if peer_entry.get("tag") != entry.get("tag"):
        return [
            f"  {name}: tag {entry.get('tag')!r} does not match "
            f"[packages.{peer_name}].tag = {peer_entry.get('tag')!r}"
        ]
    return []


def check(quiet: bool = False) -> int:
    manifest = tomllib.loads(MANIFEST_PATH.read_text())
    services = manifest.get("services", {})
    problems: list[str] = []
    checked = 0

    for name, entry in services.items():
        if entry.get("kind") != "sibling":
            continue
        checked += 1

        problems.extend(_check_tag_alignment(manifest, name, entry))

        local_path = SYSTEMD_DIR / entry["unit"]
        if not local_path.exists():
            problems.append(
                f"  {name}: local unit file missing at {local_path}"
            )
            continue
        local_text = local_path.read_text()

        try:
            upstream_text = _gh_raw_contents(
                entry["source"], entry["tag"], entry["source_path"]
            )
        except FetchError as e:
            problems.append(f"  {name}: {e}")
            continue

        up = _canonicalize(upstream_text)
        lo = _canonicalize(local_text)
        problems.extend(_diff_canonical(up, lo, name))

    if problems:
        if not quiet:
            print(
                f"services-drift: {len(problems)} issue(s) across "
                f"{checked} sibling service(s):",
                file=sys.stderr,
            )
            for p in problems:
                print(p, file=sys.stderr)
            print(
                "\nFix by either (a) updating files/systemd/<unit> to "
                "match upstream, or (b) bumping the sibling's tag in "
                "manifest.toml if upstream is what we want to adopt.",
                file=sys.stderr,
            )
        return 1
    if not quiet:
        print(f"services-drift: {checked} sibling service(s) OK")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="check_services_drift",
        description=__doc__,
    )
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args(argv)
    return check(quiet=args.quiet)


if __name__ == "__main__":
    sys.exit(main())
