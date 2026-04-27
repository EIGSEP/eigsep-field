"""eigsep-field CLI: info / verify / doctor / services / _apply-role.

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
from eigsep_field._services import (
    KNOWN_ROLES,
    ROLE_FILE,
    RoleConfig,
    is_active,
    is_enabled,
    parse_role_file,
    services_for_role,
    systemctl,
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


def _check_firmware(manifest: dict) -> tuple[list[str], list[str]]:
    """Return (ok, problems) for firmware blobs under /opt/eigsep/firmware."""
    ok: list[str] = []
    problems: list[str] = []
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
    return ok, problems


def _check_packages(manifest: dict) -> tuple[list[str], list[str]]:
    """Return (ok, problems) for every blessed Python package."""
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
    return ok, problems


def _check_services(
    manifest: dict, role_cfg: RoleConfig
) -> tuple[list[str], list[str]]:
    """Return (ok, problems) for every [services.*] entry, role-aware."""
    ok: list[str] = []
    problems: list[str] = []
    services = manifest.get("services", {})
    expected = {
        n for n, _ in services_for_role(services, role_cfg.role, role_cfg.dhcp)
    }
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
        if is_active(unit):
            ok.append(f"{unit} active ({tag})")
        else:
            problems.append(f"{unit} not active ({tag})")
    return ok, problems


def _cmd_doctor(_: argparse.Namespace) -> int:
    manifest = load_manifest()
    role_cfg = parse_role_file(ROLE_FILE)
    role_str = role_cfg.role or "unset"
    dhcp_str = " +dhcp" if role_cfg.dhcp else ""
    print(f"role: {role_str}{dhcp_str}")
    if role_cfg.role is None:
        print(
            "  (no /etc/eigsep/role; role-services will be reported as "
            "skipped)",
            file=sys.stderr,
        )

    fw_ok, fw_prob = _check_firmware(manifest)
    pkg_ok, pkg_prob = _check_packages(manifest)
    svc_ok, svc_prob = _check_services(manifest, role_cfg)

    for line in fw_ok + pkg_ok + svc_ok:
        print(f"  ok   {line}")
    for line in fw_prob + pkg_prob + svc_prob:
        print(f"  FAIL {line}", file=sys.stderr)

    return 1 if (fw_prob or pkg_prob or svc_prob) else 0


def _cmd_services(args: argparse.Namespace) -> int:
    """List / restart / logs for blessed services."""
    manifest = load_manifest()
    services = manifest.get("services", {})
    if args.action == "list":
        role_cfg = parse_role_file(ROLE_FILE)
        expected = {
            n
            for n, _ in services_for_role(
                services, role_cfg.role, role_cfg.dhcp
            )
        }
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
        rc, _ = systemctl("status", unit, "--no-pager")
        return rc
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


def _write_role_file(role_cfg: RoleConfig) -> None:
    ROLE_FILE.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    if role_cfg.role:
        lines.append(f"role = {role_cfg.role}")
    lines.append(f"dhcp = {'true' if role_cfg.dhcp else 'false'}")
    ROLE_FILE.write_text("\n".join(lines) + "\n")


DHCP_MASTER_STATIC_IP = "10.10.10.10/24"
_DHCPCD_BEGIN = "# BEGIN eigsep-field (managed)"
_DHCPCD_END = "# END eigsep-field"


def _apply_dhcp_master_static_ip(role_cfg: RoleConfig) -> int:
    """Pin eth0 to 10.10.10.10/24 on the dhcp-master Pi.

    isc-dhcp-server can't bind without a static IP on the interface
    it serves, and the rest of the LAN expects to reach the
    dhcp-master at 10.10.10.10. We rewrite a managed block in
    /etc/dhcpcd.conf (Raspberry Pi OS Lite's default DHCP client)
    between BEGIN/END markers, then restart dhcpcd. Idempotent:
    re-running replaces the block in place.

    No-op when role_cfg.dhcp is False.
    """
    if not role_cfg.dhcp:
        return 0
    conf = Path("/etc/dhcpcd.conf")
    if not conf.exists():
        print(
            f"  warn: {conf} missing; cannot pin dhcp-master static IP",
            file=sys.stderr,
        )
        return 1
    block = (
        f"{_DHCPCD_BEGIN} — dhcp-master static IP.\n"
        "# eigsep-field rewrites this block on every role apply.\n"
        "# Authority: image/pi-gen-config/stage-eigsep/.\n"
        "interface eth0\n"
        f"static ip_address={DHCP_MASTER_STATIC_IP}\n"
        f"{_DHCPCD_END}\n"
    )
    existing = conf.read_text()
    if _DHCPCD_BEGIN in existing and _DHCPCD_END in existing:
        before, _, rest = existing.partition(_DHCPCD_BEGIN)
        _, _, after = rest.partition(_DHCPCD_END + "\n")
        new = before.rstrip() + "\n\n" + block + after.lstrip()
    else:
        new = existing.rstrip() + "\n\n" + block
    conf.write_text(new)
    rc, msg = systemctl("restart", "dhcpcd.service")
    if rc != 0:
        print(f"  warn: dhcpcd restart failed: {msg}", file=sys.stderr)
        return 1
    print(f"  dhcp-master: pinned eth0 to {DHCP_MASTER_STATIC_IP}")
    return 0


def _apply_chrony_snippet(role_cfg: RoleConfig) -> int:
    """Symlink the role-appropriate chrony snippet and reload chrony.

    The snippets are staged into /etc/eigsep/chrony/ at image build
    time. Here we pick server.conf (dhcp-master) or client.conf (rest)
    and link it as /etc/chrony/conf.d/eigsep.conf — chrony's default
    config already does ``confdir /etc/chrony/conf.d``, so the snippet
    is additive.
    """
    src_dir = Path("/etc/eigsep/chrony")
    snippet = src_dir / ("server.conf" if role_cfg.dhcp else "client.conf")
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
    """First-boot hook: apply /boot/eigsep-role.conf and self-disable."""
    path = Path(args.role_conf)
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
    targets = services_for_role(services, role_cfg.role, role_cfg.dhcp)

    failed = 0
    # Pin the static IP before role services come up — isc-dhcp-server
    # binds to eth0 and needs the address ready first.
    failed += _apply_dhcp_master_static_ip(role_cfg)

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

    # Hidden: invoked only by eigsep-first-boot.service.
    ar = sub.add_parser("_apply-role", help=argparse.SUPPRESS)
    ar.add_argument("role_conf", help="path to eigsep-role.conf")
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
