"""eigsep-field CLI: info / verify / doctor / services / patch / revert /
capture / src / _apply-role.

Intentionally does **not** import sibling packages at module import time.
``doctor`` must run even when the stack is broken.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from eigsep_field import load_manifest
from eigsep_field._patch import (
    CAPTURES_DIR,
    all_firmware_targets,
    all_siblings,
    blessed_commit,
    build_capture,
    dirty_count,
    editable_source,
    git_head,
    has_active_firmware_patch,
    install_editable,
    list_firmware_target_names,
    list_sibling_names,
    patch_firmware,
    require_root,
    resolve_firmware_target,
    resolve_sibling,
    restart_units,
    revert_all,
    revert_firmware,
    revert_package,
)
from eigsep_field._services import (
    KNOWN_ROLES,
    ROLE_FILE,
    BOOT_ROLE_CONF,
    RoleConfig,
    entry_for_role,
    is_active,
    is_enabled,
    nmcli,
    parse_role_file,
    services_for_role,
    services_importing_package,
    systemctl,
    unit_health,
)


def _versions_equal(a: str, b: str) -> bool:
    """Compare versions through PEP 440 normalization (e.g. 04 == 4)."""
    try:
        from packaging.version import Version

        return Version(a) == Version(b)
    except Exception:
        return a == b


def _cmd_info(_: argparse.Namespace) -> int:
    manifest = load_manifest()
    image = manifest.get("image", {})
    if image.get("dev"):
        sha = image.get("sha", "unknown")
        print(f"*** DEV BUILD {sha} — not a blessed release ***")
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

    # Hardware-only packages (e.g. casperfpga). Not installed on CI/dev —
    # MISSING is informational here; only DRIFT fails.
    for name, entry in manifest.get("hardware", {}).items():
        blessed = entry["version"]
        try:
            installed = version(name)
        except PackageNotFoundError:
            installed = "(not installed)"
            status = "hw-only"
        else:
            status = "ok" if _versions_equal(installed, blessed) else "DRIFT"
            if status == "DRIFT":
                any_drift = True
        print(f"{name:<24} {blessed:<12} {installed:<12} {status}")

    # Field-debug packages (e.g. ipython). Only installed via the
    # `[debug]` extra (wheelhouse uses --extra debug). MISSING is
    # informational — debug isn't required for a healthy stack.
    for name, entry in manifest.get("debug", {}).items():
        pypi_name = entry["pypi"]
        blessed = entry["version"]
        try:
            installed = version(pypi_name)
        except PackageNotFoundError:
            installed = "(not installed)"
            status = "debug"
        else:
            status = "ok" if _versions_equal(installed, blessed) else "DRIFT"
            if status == "DRIFT":
                any_drift = True
        print(f"{pypi_name:<24} {blessed:<12} {installed:<12} {status}")

    # External binaries (e.g. cmtvna). Proprietary, operator-installed
    # via scripts/install-cmtvna.sh. Reported on every Pi (doctor's
    # role-aware check is where missing-on-applicable-role becomes a FAIL).
    for name, entry in manifest.get("external", {}).items():
        blessed = entry["version"]
        binary = Path(entry["install_path"]) / entry["binary"]
        if binary.is_file() and os.access(binary, os.X_OK):
            installed = "present"
            status = "ok"
        else:
            installed = "(not installed)"
            status = "external"
        print(f"{name:<24} {blessed:<12} {installed:<12} {status}")
    return 1 if any_drift else 0


def _cmd_verify(_: argparse.Namespace) -> int:
    """Run eigsep_observing's producer-contract tests if available.

    The suite ships inside the eigsep_observing wheel (under
    ``eigsep_observing.contract_tests``) so this works on wheel-only
    installs — no test-tree checkout required.
    """
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
        "eigsep_observing.contract_tests",
    ]
    return subprocess.run(cmd).returncode


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _check_firmware(
    manifest: dict, role_cfg: RoleConfig
) -> tuple[list[str], list[str]]:
    """Return (ok, problems) for firmware blobs under /opt/eigsep/firmware.

    Role-aware: a ``[firmware.<kind>]`` entry with ``roles = [...]`` is
    only checked when the running Pi's role matches one of the listed
    roles. Entries without ``roles`` are checked on every Pi.
    """
    ok: list[str] = []
    problems: list[str] = []
    firmware_root = Path("/opt/eigsep/firmware")
    for kind, entry in manifest.get("firmware", {}).items():
        if not entry_for_role(entry, role_cfg.role):
            ok.append(
                f"{kind}: skipped (not this role — roles={entry['roles']})"
            )
            continue
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
    return ok, problems


def _check_external(
    manifest: dict, role_cfg: RoleConfig
) -> tuple[list[str], list[str]]:
    """Return (ok, problems) for [external.*] binaries.

    Role-aware via ``roles = [...]`` — proprietary binaries are tied to
    the Pi roles that import them. Missing on a non-matching role is
    "skipped"; missing on a matching role is a FAIL with a hint at the
    operator install command.
    """
    ok: list[str] = []
    problems: list[str] = []
    for name, entry in manifest.get("external", {}).items():
        if not entry_for_role(entry, role_cfg.role):
            ok.append(
                f"{name}: skipped (not this role — roles={entry['roles']})"
            )
            continue
        binary = Path(entry["install_path"]) / entry["binary"]
        if not binary.is_file():
            problems.append(
                f"{name}: missing {binary} "
                f"(operator install: "
                f"sudo /opt/eigsep/src/eigsep-field/scripts/install-{name}.sh)"
            )
            continue
        if not os.access(binary, os.X_OK):
            problems.append(f"{name}: {binary} present but not executable")
            continue
        ok.append(f"{name}: {binary} present (manifest v{entry['version']})")
    return ok, problems


def _check_packages(
    manifest: dict, role_cfg: RoleConfig
) -> tuple[list[str], list[str]]:
    """Return (ok, problems) for every blessed Python package.

    ``[packages.*]`` entries are checked on every Pi (they're the core
    stack). ``[hardware.*]`` entries are role-aware via ``roles = [...]``
    on the manifest entry — e.g. casperfpga is only required on backend.
    """
    ok: list[str] = []
    problems: list[str] = []
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

    for name, entry in manifest.get("hardware", {}).items():
        if not entry_for_role(entry, role_cfg.role):
            ok.append(
                f"{name}: skipped (not this role — roles={entry['roles']})"
            )
            continue
        blessed = entry["version"]
        try:
            installed = version(name)
        except PackageNotFoundError:
            problems.append(
                f"{name}: not installed (hardware, blessed {blessed})"
            )
            continue
        if not _versions_equal(installed, blessed):
            problems.append(
                f"{name}: installed {installed}, blessed {blessed}"
            )
        else:
            ok.append(f"{name}: {installed} (hardware)")

    # Debug packages: missing is *not* a problem (the debug extra is
    # opt-in), but a version mismatch is — it means the wheelhouse and
    # the manifest disagree, and `eigsep-field info` would also show DRIFT.
    for entry in manifest.get("debug", {}).values():
        pypi_name = entry["pypi"]
        blessed = entry["version"]
        try:
            installed = version(pypi_name)
        except PackageNotFoundError:
            ok.append(f"{pypi_name}: not installed (debug, blessed {blessed})")
            continue
        if not _versions_equal(installed, blessed):
            problems.append(
                f"{pypi_name}: installed {installed}, blessed {blessed}"
            )
        else:
            ok.append(f"{pypi_name}: {installed} (debug)")
    return ok, problems


def _check_services(
    manifest: dict, role_cfg: RoleConfig
) -> tuple[list[str], list[str]]:
    """Return (ok, problems) for every [services.*] entry, role-aware."""
    ok: list[str] = []
    problems: list[str] = []
    services = manifest.get("services", {})
    expected = {n for n, _ in services_for_role(services, role_cfg.role)}
    for name, entry in services.items():
        unit = entry["unit"]
        activation = entry.get("activation")
        tag = (
            "always"
            if activation == "always"
            else f"role: {entry.get('role', '?')}"
        )
        if name not in expected:
            ok.append(f"{unit} skipped (not this role — {tag})")
            continue
        healthy, state = unit_health(unit)
        if healthy:
            ok.append(f"{unit} {state} ({tag})")
        else:
            problems.append(f"{unit} {state} ({tag})")
    return ok, problems


def _check_editable_drift(manifest: dict) -> list[str]:
    """Advisory notes for siblings that are editable, drifted, or dirty.

    These are operator-visible state changes (active hot-patches), not
    failures — the field workflow expects siblings to go editable
    temporarily, so this returns advisories that don't fail doctor.
    """
    notes: list[str] = []
    for s in all_siblings(manifest):
        if not s.src_path.exists():
            continue
        flags: list[str] = []
        ed_src = editable_source(s.pypi_name)
        if ed_src is not None:
            flags.append(f"editable -> {ed_src}")
        head = git_head(s.src_path)
        base = blessed_commit(s.src_path)
        if head and base and head != base:
            flags.append(f"drifted blessed={base[:8]} head={head[:8]}")
        n = dirty_count(s.src_path)
        if n:
            flags.append(f"dirty ({n} uncommitted)")
        if not flags:
            continue
        line = f"{s.name}: " + "; ".join(flags)
        units = services_importing_package(manifest, s.pypi_name)
        if units:
            line += f"  [services: {', '.join(units)}]"
        notes.append(line)
    return notes


def _check_firmware_patches(manifest: dict) -> list[str]:
    """Surface active firmware drop-in overrides as advisory notes.

    When the operator has run ``eigsep-field patch pico-firmware``, a
    drop-in retargets the unit's --uf2 flag at the field-built UF2.
    This must be operator-visible from a cold ssh so a stale hotfix
    doesn't haunt the next campaign.
    """
    notes: list[str] = []
    for t in all_firmware_targets(manifest):
        if not has_active_firmware_patch(t):
            continue
        notes.append(
            f"{t.name}: field-patched UF2 active -> {t.field_uf2}  "
            f"[service: {t.service_unit}; revert: "
            f"`sudo eigsep-field revert {t.name}`]"
        )
    return notes


def _cmd_doctor(_: argparse.Namespace) -> int:
    manifest = load_manifest()
    role_cfg = parse_role_file(ROLE_FILE)
    role_str = role_cfg.role or "unset"
    print(f"role: {role_str}")
    if role_cfg.role is None:
        print(
            "  (no /etc/eigsep/role; role-services will be reported as "
            "skipped)",
            file=sys.stderr,
        )

    fw_ok, fw_prob = _check_firmware(manifest, role_cfg)
    pkg_ok, pkg_prob = _check_packages(manifest, role_cfg)
    svc_ok, svc_prob = _check_services(manifest, role_cfg)
    ext_ok, ext_prob = _check_external(manifest, role_cfg)
    notes = _check_editable_drift(manifest) + _check_firmware_patches(manifest)

    for line in fw_ok + pkg_ok + svc_ok + ext_ok:
        print(f"  ok   {line}")
    for line in notes:
        print(f"  note {line}")
    for line in fw_prob + pkg_prob + svc_prob + ext_prob:
        print(f"  FAIL {line}", file=sys.stderr)

    return 1 if (fw_prob or pkg_prob or svc_prob or ext_prob) else 0


def _cmd_services(args: argparse.Namespace) -> int:
    """List / restart / logs for blessed services."""
    manifest = load_manifest()
    services = manifest.get("services", {})
    if args.action == "list":
        role_cfg = parse_role_file(ROLE_FILE)
        expected = {n for n, _ in services_for_role(services, role_cfg.role)}
        hdr = f"{'name':<24} {'unit':<32} {'scope':<20} {'state':<20}"
        print(hdr)
        print("-" * len(hdr))
        for name, entry in services.items():
            unit = entry["unit"]
            activation = entry.get("activation", "?")
            scope = (
                "always"
                if activation == "always"
                else f"role: {entry.get('role', '?')}"
            )
            if name in expected:
                state = (
                    f"{'active' if is_active(unit) else 'inactive'}/"
                    f"{'enabled' if is_enabled(unit) else 'disabled'}"
                )
            else:
                state = "skipped"
            print(f"{name:<24} {unit:<32} {scope:<20} {state:<20}")
        return 0

    # restart / logs / status target a specific service by manifest name.
    if args.name not in services:
        print(
            f"unknown service {args.name!r}; see `eigsep-field services list`",
            file=sys.stderr,
        )
        return 2
    unit = services[args.name]["unit"]

    if args.action == "status":
        # Stream directly to the terminal — the `systemctl()` helper
        # captures stdout/stderr (right for is_active / unit_health, wrong
        # for an interactive status dump that the operator needs to read).
        return subprocess.run(
            ["systemctl", "status", unit, "--no-pager"]
        ).returncode
    if args.action == "restart":
        rc, msg = systemctl("restart", unit)
        if rc != 0:
            print(f"restart {unit} failed: {msg}", file=sys.stderr)
        return rc
    if args.action == "logs":
        cmd = ["journalctl", "-u", unit]
        if args.follow:
            cmd.append("-f")
        return subprocess.run(cmd).returncode
    raise AssertionError(f"unhandled services action: {args.action}")


def _unknown_target(manifest: dict, name: str) -> int:
    names = sorted(
        list_sibling_names(manifest) + list_firmware_target_names(manifest)
    )
    print(
        f"unknown target {name!r}; known: {', '.join(names)}",
        file=sys.stderr,
    )
    return 2


def _cmd_patch(args: argparse.Namespace) -> int:
    manifest = load_manifest()
    # Firmware targets are resolved first so an operator typing
    # `pico-firmware` always lands in the build+flash flow, never in a
    # surprise Python-editable install of a same-named sibling.
    fw = resolve_firmware_target(manifest, args.name)
    if fw is not None:
        print(f"firmware target: {fw.name} -> {fw.src_path}")
        print(f"build:           {fw.src_path / fw.script}")
        print(f"will reflash:    {fw.service_unit}")
        if args.dry_run:
            return 0
        rc = require_root("patch")
        if rc is not None:
            return rc
        return patch_firmware(fw)

    sibling = resolve_sibling(manifest, args.name)
    if sibling is None:
        return _unknown_target(manifest, args.name)
    if not (sibling.src_path / ".git").exists():
        print(
            f"no source tree at {sibling.src_path} (or no .git/)",
            file=sys.stderr,
        )
        return 2
    units = services_importing_package(manifest, sibling.pypi_name)
    print(f"sibling: {sibling.name} -> {sibling.src_path}")
    print(f"editable install: {sibling.pypi_name}")
    if units:
        print(f"will restart: {', '.join(units)}")
    else:
        print("no services to restart for this sibling")
    if args.dry_run:
        return 0
    rc = require_root("patch")
    if rc is not None:
        return rc
    rc = install_editable(sibling)
    if rc != 0:
        print("editable install failed", file=sys.stderr)
        return rc
    if args.no_restart or not units:
        return 0
    _, failed = restart_units(units)
    return 1 if failed else 0


def _cmd_revert(args: argparse.Namespace) -> int:
    manifest = load_manifest()
    if args.name and args.all:
        print(
            "--all and a sibling name are mutually exclusive",
            file=sys.stderr,
        )
        return 2
    rc = require_root("revert")
    if rc is not None:
        return rc

    if args.name:
        fw = resolve_firmware_target(manifest, args.name)
        if fw is not None:
            return revert_firmware(fw)

    units: list[str] = []
    if args.name:
        sibling = resolve_sibling(manifest, args.name)
        if sibling is None:
            return _unknown_target(manifest, args.name)
        rc = revert_package(sibling)
        units = services_importing_package(manifest, sibling.pypi_name)
    else:
        rc = revert_all()
        # `uv sync` reinstalls every wheel; restart only the sibling
        # services this Pi's role actually runs.
        role_cfg = parse_role_file(ROLE_FILE)
        services = manifest.get("services", {})
        for _, entry in services_for_role(services, role_cfg.role):
            if entry.get("kind") == "sibling":
                units.append(entry["unit"])
    if rc != 0:
        return rc
    if args.no_restart or not units:
        return 0
    _, failed = restart_units(units)
    return 1 if failed else 0


def _cmd_capture(args: argparse.Namespace) -> int:
    from datetime import datetime, timezone

    manifest = load_manifest()
    sibling = resolve_sibling(manifest, args.name)
    if sibling is None:
        return _unknown_target(manifest, args.name)
    text = build_capture(sibling, manifest)
    if text is None:
        print(f"no changes to capture for {sibling.name}")
        return 0
    if args.out:
        out = Path(args.out)
    else:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out = CAPTURES_DIR / f"{sibling.name}-{ts}.patch"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text)
    print(f"wrote {out}")
    print(
        f"  scp the .patch back to base, then `git apply` against {sibling.name}"
    )
    return 0


def _cmd_src(args: argparse.Namespace) -> int:
    manifest = load_manifest()
    sibling = resolve_sibling(manifest, args.name)
    if sibling is None:
        return _unknown_target(manifest, args.name)
    if not sibling.src_path.exists():
        print(
            f"no source tree at {sibling.src_path}",
            file=sys.stderr,
        )
        return 2
    print(sibling.src_path)
    return 0


def _write_role_file(role_cfg: RoleConfig) -> None:
    ROLE_FILE.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    if role_cfg.role:
        lines.append(f"role = {role_cfg.role}")
    ROLE_FILE.write_text("\n".join(lines) + "\n")


ROLE_STATIC_IPS = {
    "backend": "10.10.10.10/24",
    "panda": "10.10.10.11/24",
}
NM_CONNECTION_NAME = "eigsep-eth0"
NM_CONNECTIONS_DIR = Path("/etc/NetworkManager/system-connections")


def _apply_role_static_ip(
    role_cfg: RoleConfig, nm_dir: Path = NM_CONNECTIONS_DIR
) -> int:
    """Pin eth0 to the role's static address.

    Backend gets 10.10.10.10/24 (isc-dhcp-server can't bind without a
    static IP on the interface it serves, and the LAN expects to reach
    the DHCP server at 10.10.10.10). Panda gets 10.10.10.11/24 so a
    freshly-flashed panda is reachable on the bench from the operator
    laptop without needing the backend Pi on the wire.

    Trixie pi-gen Lite uses NetworkManager (the dhcpcd binary is present
    but ships no systemd unit), so we drop a keyfile in NM's
    system-connections directory and ask nmcli to reload + activate it.
    Idempotent: re-running overwrites the keyfile in place.

    No-op when the role has no entry in ROLE_STATIC_IPS.
    """
    static_ip = ROLE_STATIC_IPS.get(role_cfg.role or "")
    if static_ip is None:
        return 0
    if not nm_dir.exists():
        print(
            f"  warn: {nm_dir} missing; cannot pin {role_cfg.role} static IP",
            file=sys.stderr,
        )
        return 1
    keyfile = nm_dir / f"{NM_CONNECTION_NAME}.nmconnection"
    keyfile.write_text(
        "# Authority: image/pi-gen-config/stage-eigsep/.\n"
        "# eigsep-field rewrites this file on every role apply.\n"
        "[connection]\n"
        f"id={NM_CONNECTION_NAME}\n"
        "type=ethernet\n"
        "interface-name=eth0\n"
        "autoconnect=true\n"
        "autoconnect-priority=100\n"
        "\n"
        "[ethernet]\n"
        "\n"
        "[ipv4]\n"
        "method=manual\n"
        f"address1={static_ip}\n"
        "never-default=true\n"
        "\n"
        "[ipv6]\n"
        "method=disabled\n"
    )
    # NetworkManager refuses to load world-readable keyfiles.
    keyfile.chmod(0o600)
    rc, msg = nmcli("connection", "reload")
    if rc != 0:
        print(f"  warn: nmcli reload failed: {msg}", file=sys.stderr)
        return 1
    rc, msg = nmcli("connection", "up", NM_CONNECTION_NAME)
    if rc != 0:
        print(
            f"  warn: nmcli up {NM_CONNECTION_NAME} failed: {msg}",
            file=sys.stderr,
        )
        return 1
    print(f"  {role_cfg.role}: pinned eth0 to {static_ip}")
    return 0


def _apply_chrony_snippet(role_cfg: RoleConfig) -> int:
    """Symlink the role-appropriate chrony snippet and reload chrony.

    The snippets are staged into /etc/eigsep/chrony/ at image build
    time. The backend Pi gets server.conf (it's the LAN time server);
    every other role gets client.conf. The snippet is linked at
    /etc/chrony/conf.d/eigsep.conf — chrony's default config already
    does ``confdir /etc/chrony/conf.d``, so the snippet is additive.
    """
    src_dir = Path("/etc/eigsep/chrony")
    is_server = role_cfg.role == "backend"
    snippet = src_dir / ("server.conf" if is_server else "client.conf")
    target = Path("/etc/chrony/conf.d/eigsep.conf")
    if not snippet.exists():
        print(
            f"  warn: {snippet} missing; chrony unchanged",
            file=sys.stderr,
        )
        return 1
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink() or target.exists():
        target.unlink()
    target.symlink_to(snippet)
    rc, msg = systemctl("reload-or-restart", "chrony.service")
    if rc != 0:
        print(f"  warn: chrony reload failed: {msg}", file=sys.stderr)
        return 1
    print(f"  chrony: {target} -> {snippet}")
    return 0


def _cmd_apply_role(args: argparse.Namespace) -> int:
    """First-boot hook: apply the operator's role conf and self-disable."""
    path = Path(args.role_conf) if args.role_conf else BOOT_ROLE_CONF
    role_cfg = parse_role_file(path)
    if role_cfg.role is None:
        print(f"{path}: no role= line found", file=sys.stderr)
        return 2
    if role_cfg.role not in KNOWN_ROLES:
        print(
            f"{path}: unknown role {role_cfg.role!r}; "
            f"known roles: {sorted(KNOWN_ROLES)}",
            file=sys.stderr,
        )
        return 2

    manifest = load_manifest()
    services = manifest.get("services", {})
    targets = services_for_role(services, role_cfg.role)

    failed = 0
    # Pin the static IP before role services come up — isc-dhcp-server
    # binds to eth0 and needs the address ready first.
    failed += _apply_role_static_ip(role_cfg)

    for name, entry in targets:
        if entry.get("activation") != "role":
            # Always-services are already enabled at image build time.
            continue
        unit = entry["unit"]
        rc, msg = systemctl("enable", "--now", unit)
        if rc == 0:
            print(f"  enabled {unit} ({name})")
        else:
            failed += 1
            print(f"  FAIL enable {unit} ({name}): {msg}", file=sys.stderr)

    failed += _apply_chrony_snippet(role_cfg)

    _write_role_file(role_cfg)

    # Self-disable so re-rolling requires an explicit
    # `systemctl enable eigsep-first-boot.service` after editing the conf.
    rc, msg = systemctl("disable", "eigsep-first-boot.service")
    if rc != 0:
        print(
            f"  warn: could not self-disable eigsep-first-boot: {msg}",
            file=sys.stderr,
        )

    return 1 if failed else 0


def _add_services_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "services", help="list/status/restart/logs for blessed services"
    )
    p.set_defaults(func=_cmd_services)
    svc_sub = p.add_subparsers(dest="action", required=True)
    svc_sub.add_parser("list", help="table of services + scope + state")
    for action in ("status", "restart"):
        sp = svc_sub.add_parser(action, help=f"systemctl {action} <unit>")
        sp.add_argument(
            "name", help="manifest service name (e.g. picomanager)"
        )
    sp = svc_sub.add_parser("logs", help="journalctl -u <unit>")
    sp.add_argument("name", help="manifest service name (e.g. picomanager)")
    sp.add_argument("-f", "--follow", action="store_true")


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
        "doctor", help="check role, firmware, packages, services"
    ).set_defaults(func=_cmd_doctor)
    _add_services_parser(sub)

    patch = sub.add_parser(
        "patch",
        help="install a sibling editable, or rebuild+reflash a firmware "
        "target, from /opt/eigsep/src (needs sudo)",
    )
    patch.set_defaults(func=_cmd_patch)
    patch.add_argument(
        "name",
        help="sibling TOML key (e.g. eigsep_observing) or firmware "
        "target (e.g. pico-firmware)",
    )
    patch.add_argument(
        "--no-restart",
        action="store_true",
        help="skip systemctl restart of importing units",
    )
    patch.add_argument(
        "--dry-run",
        action="store_true",
        help="print plan, do not modify the venv",
    )

    revert = sub.add_parser(
        "revert",
        help="restore a sibling, firmware target, or everything to the "
        "blessed wheelhouse (needs sudo)",
    )
    revert.set_defaults(func=_cmd_revert)
    revert.add_argument(
        "name",
        nargs="?",
        help="sibling TOML key or firmware target (e.g. pico-firmware); "
        "omit (or pass --all) for full uv sync",
    )
    revert.add_argument(
        "--all",
        action="store_true",
        help="uv sync the whole venv to the lockfile",
    )
    revert.add_argument(
        "--no-restart",
        action="store_true",
        help="skip systemctl restart of importing units",
    )

    capture = sub.add_parser(
        "capture",
        help="write a .patch from current sibling state for sneakernet",
    )
    capture.set_defaults(func=_cmd_capture)
    capture.add_argument(
        "name", help="sibling TOML key (e.g. eigsep_observing)"
    )
    capture.add_argument(
        "--out",
        default=None,
        help="output path (default /opt/eigsep/captures/<name>-<ts>.patch)",
    )

    src = sub.add_parser(
        "src",
        help="print the path to a sibling's source tree",
    )
    src.set_defaults(func=_cmd_src)
    src.add_argument("name", help="sibling TOML key (e.g. eigsep_observing)")

    # Hidden: invoked only by eigsep-first-boot.service.
    ar = sub.add_parser("_apply-role", help=argparse.SUPPRESS)
    ar.add_argument(
        "role_conf",
        nargs="?",
        default=None,
        help=f"path to eigsep-role.conf (default: {BOOT_ROLE_CONF})",
    )
    ar.set_defaults(func=_cmd_apply_role)

    args = p.parse_args(argv)
    # Defensive: /etc/eigsep/role writes need root; flag it early for the
    # one subcommand that actually writes.
    if getattr(args, "func", None) is _cmd_apply_role and os.geteuid() != 0:
        print("_apply-role must run as root", file=sys.stderr)
        return 2
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
