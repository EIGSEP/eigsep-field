"""eigsep-field — umbrella for the EIGSEP field stack."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

try:
    __version__ = version("eigsep-field")
except PackageNotFoundError:
    __version__ = "0+unknown"


def load_manifest() -> dict:
    """Return the blessed manifest as a dict.

    Reads the installed copy (``_manifest.toml``) if present; falls back
    to the repo-root ``manifest.toml`` for editable installs.
    """
    import tomllib

    here = Path(__file__).resolve()
    candidates = [
        here.parent / "_manifest.toml",
        here.parent.parent.parent / "manifest.toml",
    ]
    for p in candidates:
        if p.exists():
            return tomllib.loads(p.read_text())
    raise FileNotFoundError(
        "manifest.toml not found next to package or at repo root"
    )
