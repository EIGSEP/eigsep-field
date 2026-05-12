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

# Operator-supplied role config dropped on the SD card's FAT boot
# partition. Trixie's pi-gen mounts that partition at /boot/firmware
# (preferred); older Bullseye/Bookworm SDs mounted it at /boot.
# resolve_boot_role_conf() returns whichever exists, preferring the
# Trixie path.
BOOT_ROLE_CONF_CANDIDATES: tuple[Path, ...] = (
    Path("/boot/firmware/eigsep-role.conf"),
    Path("/boot/eigsep-role.conf"),
)

KNOWN_ROLES = {"panda", "backend"}


def resolve_boot_role_conf(
    candidates: tuple[Path, ...] = BOOT_ROLE_CONF_CANDIDATES,
) -> Path:
    """Return the first existing candidate, or candidates[0] if none exist.

    Returning the preferred path on miss (rather than ``None``) keeps
    error messages pointed at the canonical location.
    """
    for c in candidates:
        if c.exists():
            return c
    return candidates[0]


@dataclass(frozen=True)
class RoleConfig:
    role: str | None


def parse_role_file(path: Path) -> RoleConfig:
    """Parse ``role = <name>`` from a text file.

    Same format for ``/boot/firmware/eigsep-role.conf`` (operator input) and
    ``/etc/eigsep/role`` (applied state). Missing file → empty config
    (callers decide whether that's an error). Unknown keys (including
    the legacy ``dhcp =`` line) are ignored so old role files on
    pre-existing SD cards don't break first-boot.
    """
    role: str | None = None
    if not path.exists():
        return RoleConfig(role=None)
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
    return RoleConfig(role=role)


def services_for_role(
    services: dict, role: str | None
) -> list[tuple[str, dict]]:
    """Return service entries that should be enabled on this Pi.

    Always services are always included. Role services match ``role``
    exactly. Order preserved from the manifest.
    """
    out: list[tuple[str, dict]] = []
    for name, entry in services.items():
        activation = entry.get("activation")
        if activation == "always":
            out.append((name, entry))
            continue
        if activation != "role":
            continue
        if entry.get("role") == role:
            out.append((name, entry))
    return out


def systemctl(*args: str) -> tuple[int, str]:
    """Run ``systemctl <args...>``; return (rc, combined stderr/stdout)."""
    r = subprocess.run(["systemctl", *args], capture_output=True, text=True)
    msg = (r.stderr or r.stdout).strip()
    return r.returncode, msg


def nmcli(*args: str) -> tuple[int, str]:
    """Run ``nmcli <args...>``; return (rc, combined stderr/stdout)."""
    r = subprocess.run(["nmcli", *args], capture_output=True, text=True)
    msg = (r.stderr or r.stdout).strip()
    return r.returncode, msg


def is_active(unit: str) -> bool:
    rc, _ = systemctl("is-active", "--quiet", unit)
    return rc == 0


def is_enabled(unit: str) -> bool:
    rc, _ = systemctl("is-enabled", "--quiet", unit)
    return rc == 0


def unit_health(unit: str) -> tuple[bool, str]:
    """Return ``(healthy, state)`` for a systemd unit.

    Long-running services are healthy when ``ActiveState=active``.
    Oneshot services with ``RemainAfterExit=no`` (like
    ``eigsep-first-boot.service``) return to ``inactive`` after a clean
    exit — ``is_active`` would falsely flag them as broken. We consult
    ``systemctl show`` to distinguish "ran successfully and exited" from
    "never ran" or "failed".

    ``state`` is a short human-readable string for doctor output.
    """
    if is_active(unit):
        return True, "active"
    rc, out = systemctl(
        "show", "--value", "-p", "Type,RemainAfterExit,Result", unit
    )
    if rc != 0:
        return False, "inactive"
    parts = out.splitlines()
    type_ = parts[0] if len(parts) > 0 else ""
    remain = parts[1] if len(parts) > 1 else ""
    result = parts[2] if len(parts) > 2 else ""
    if type_ == "oneshot" and remain == "no" and result == "success":
        return True, "oneshot done"
    return False, "inactive"


def entry_for_role(entry: dict, role: str | None) -> bool:
    """Return ``True`` if a ``[firmware.*]`` / ``[hardware.*]`` entry
    applies to the given role.

    Entries without a ``roles`` field default to all roles (back-compat).
    Entries with an explicit ``roles = [...]`` list are checked only
    against the named roles. ``role=None`` (no role applied yet) skips
    role-scoped entries entirely so the doctor doesn't fail on a freshly
    flashed Pi where /etc/eigsep/role hasn't been written.
    """
    roles = entry.get("roles")
    if roles is None:
        return True
    if role is None:
        return False
    return role in roles


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


def peer_package_for_service(
    manifest: dict, service_entry: dict
) -> tuple[str, dict] | None:
    """Return ``(name, entry)`` for the ``[packages.*]`` item that owns a
    sibling service, or ``None`` if no peer is found.

    Linked by the ``source`` URL: a ``kind="sibling"`` service entry and
    its peer package point at the same upstream git repo. Independent of
    ``tag`` — that's the field drift CI verifies *between* the two —
    so this is safe to use as the source-of-truth lookup that the drift
    checker compares against.
    """
    src = service_entry.get("source")
    if not src:
        return None
    for name, entry in manifest.get("packages", {}).items():
        if entry.get("source") == src:
            return name, entry
    return None
