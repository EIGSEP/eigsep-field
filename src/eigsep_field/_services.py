"""Helpers for manifest-driven service management.

Shared between the CLI (``doctor``, ``services``, ``_apply-role``) and the
image-build helper (``_image_install``). All functions are pure or thin
``systemctl`` wrappers — no manifest loading, no argument parsing. Callers
pass in the parsed ``manifest["services"]`` dict.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

ROLE_FILE = Path("/etc/eigsep/role")
BOOT_ROLE_CONF = Path("/boot/eigsep-role.conf")

KNOWN_ROLES = {"panda", "backend"}


@dataclass(frozen=True)
class RoleConfig:
    role: str | None
    dhcp: bool


def parse_role_file(path: Path) -> RoleConfig:
    """Parse ``role = <name>`` / ``dhcp = <bool>`` from a text file.

    Same format for ``/boot/eigsep-role.conf`` (operator input) and
    ``/etc/eigsep/role`` (applied state). Missing file → empty config
    (callers decide whether that's an error).
    """
    role: str | None = None
    dhcp = False
    if not path.exists():
        return RoleConfig(role=None, dhcp=False)
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, _, v = line.partition("=")
        key = k.strip().lower()
        val = v.strip().strip('"').strip("'").lower()
        if key == "role":
            role = val or None
        elif key == "dhcp":
            dhcp = val in ("true", "yes", "on", "1")
    return RoleConfig(role=role, dhcp=dhcp)


def services_for_role(
    services: dict, role: str | None, dhcp: bool
) -> list[tuple[str, dict]]:
    """Return service entries that should be enabled on this Pi.

    Always services are always included. Role services match ``role``
    (or ``dhcp == True`` for the ``dhcp-master`` role). Order preserved
    from the manifest.
    """
    out: list[tuple[str, dict]] = []
    for name, entry in services.items():
        activation = entry.get("activation")
        if activation == "always":
            out.append((name, entry))
            continue
        if activation != "role":
            continue
        entry_role = entry.get("role")
        if entry_role == "dhcp-master":
            if dhcp:
                out.append((name, entry))
        elif entry_role == role:
            out.append((name, entry))
    return out


def systemctl(*args: str) -> tuple[int, str]:
    """Run ``systemctl <args...>``; return (rc, combined stderr/stdout)."""
    r = subprocess.run(["systemctl", *args], capture_output=True, text=True)
    msg = (r.stderr or r.stdout).strip()
    return r.returncode, msg


def is_active(unit: str) -> bool:
    rc, _ = systemctl("is-active", "--quiet", unit)
    return rc == 0


def is_enabled(unit: str) -> bool:
    rc, _ = systemctl("is-enabled", "--quiet", unit)
    return rc == 0


def services_importing(services: dict, package_tag: str) -> list[str]:
    """Return systemd unit names whose sibling tag matches ``package_tag``.

    The manifest pins each ``kind="sibling"`` service entry to the same
    tag as the owning package (enforced by ``check_services_drift.py``),
    so equality of ``tag`` is the package→unit edge.
    """
    return [
        entry["unit"]
        for entry in services.values()
        if entry.get("kind") == "sibling" and entry.get("tag") == package_tag
    ]


def services_importing_package(manifest: dict, pypi_name: str) -> list[str]:
    """Return systemd unit names that import a given PyPI package.

    Looks the package up in ``[packages.*]`` by ``pypi`` (not by the
    TOML key, which is free-form) and finds sibling services pinned to
    the same tag. Returns ``[]`` for packages with no service of their
    own (e.g. eigsep_redis, pyvalon).
    """
    tag: str | None = None
    for entry in manifest.get("packages", {}).values():
        if entry.get("pypi") == pypi_name:
            tag = entry.get("tag")
            break
    if tag is None:
        return []
    return services_importing(manifest.get("services", {}), tag)
