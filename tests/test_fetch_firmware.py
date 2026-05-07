"""Tests for ``scripts/fetch_firmware.py`` build-time gate.

A ``[firmware.*]`` entry with an empty ``tag`` field cannot be resolved
to a Release asset; the script must fail the build rather than silently
ship an image with the asset missing.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "fetch_firmware.py"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "fetch_firmware", SCRIPT_PATH
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("fetch_firmware", mod)
    spec.loader.exec_module(mod)
    return mod


def test_missing_tag_fails(tmp_path: Path, capsys) -> None:
    manifest = tmp_path / "manifest.toml"
    manifest.write_text(
        "[firmware.thing]\n"
        'asset   = "thing.bin"\n'
        'source  = "https://github.com/example/thing"\n'
        'tag     = ""\n'
    )
    out_root = tmp_path / "out"

    fetch = _load_module()
    rc = fetch.main(["fetch_firmware.py", str(manifest), str(out_root)])

    assert rc == 1
    err = capsys.readouterr().err
    assert "thing" in err
    assert "tag" in err.lower()


def test_empty_firmware_section_is_ok(tmp_path: Path) -> None:
    """A manifest with no [firmware.*] entries must succeed (rc=0).

    The fail-fast applies to entries that exist but can't resolve, not to
    the absence of entries.
    """
    manifest = tmp_path / "manifest.toml"
    manifest.write_text("# no firmware section\n")
    out_root = tmp_path / "out"

    fetch = _load_module()
    rc = fetch.main(["fetch_firmware.py", str(manifest), str(out_root)])
    assert rc == 0
