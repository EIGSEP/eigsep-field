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

    def update(self, metadata: dict) -> None:
        root = Path(self.root)
        manifest = tomllib.loads((root / "manifest.toml").read_text())

        metadata["version"] = manifest["release"]

        deps: list[str] = []
        for entry in manifest["packages"].values():
            name = entry["pypi"]
            version = entry["version"]
            deps.append(f"{name}=={version}")
        metadata["dependencies"] = deps
