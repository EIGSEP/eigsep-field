"""Hatch metadata hook: inject dynamic version + dependencies from manifest.toml.

Runs at build time. Keeps `pyproject.toml` declarative — the only place
that names versions is `manifest.toml`.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from hatchling.metadata.plugin.interface import MetadataHookInterface


class ManifestHook(MetadataHookInterface):
    PLUGIN_NAME = "eigsep-field-manifest"

    # CI/dev tooling: floating versions are fine here — these never ship
    # to a Pi. Kept in code (not manifest.toml) because manifest.toml is
    # for *blessed, pinned* artifacts.
    DEV_EXTRAS = [
        "ruff",
        "pytest",
        "pytest-cov",
        "pytest-timeout",
        "build",
    ]

    def update(self, metadata: dict) -> None:
        root = Path(self.root)
        manifest = tomllib.loads((root / "manifest.toml").read_text())

        metadata["version"] = manifest["release"]

        deps: list[str] = []
        for entry in manifest["packages"].values():
            name = entry["pypi"]
            version = entry["version"]
            deps.append(f"{name}=={version}")
        # [tooling.*] pins are required by eigsep-field's own commands
        # (e.g. `revert` calls `uv sync`), so they live in the main
        # dependency list — not behind an extra. Same shape as packages.
        for entry in manifest.get("tooling", {}).values():
            name = entry["pypi"]
            version = entry["version"]
            deps.append(f"{name}=={version}")
        metadata["dependencies"] = deps

        # PEP 621 forbids splitting a field across static and dynamic, so
        # `dev` is set here too rather than in pyproject.toml. `debug` is
        # populated from manifest.toml's [debug.*] table — those pins go
        # to the field via the wheelhouse's --extra debug compile.
        debug_extras = [
            f"{e['pypi']}=={e['version']}"
            for e in manifest.get("debug", {}).values()
        ]
        metadata["optional-dependencies"] = {
            "dev": list(self.DEV_EXTRAS),
            "debug": debug_extras,
        }
