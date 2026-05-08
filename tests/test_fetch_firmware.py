"""Tests for ``scripts/fetch_firmware.py`` build-time gate.

The script must fail-fast (rc=1) for release builds (``--strict``) on a
``[firmware.*]`` entry it can't resolve — a blessed image must never
ship with the asset missing. DEV builds (default) warn-and-continue
(rc=0) so iteration isn't blocked while a sibling firmware repo hasn't
tagged yet.
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


def _write_unresolvable_manifest(tmp_path: Path) -> Path:
    manifest = tmp_path / "manifest.toml"
    manifest.write_text(
        "[firmware.thing]\n"
        'asset   = "thing.bin"\n'
        'source  = "https://github.com/example/thing"\n'
        'tag     = ""\n'
    )
    return manifest


def test_missing_tag_strict_fails(tmp_path: Path, capsys) -> None:
    manifest = _write_unresolvable_manifest(tmp_path)
    out_root = tmp_path / "out"

    fetch = _load_module()
    rc = fetch.main(
        ["fetch_firmware.py", str(manifest), str(out_root), "--strict"]
    )

    assert rc == 1
    err = capsys.readouterr().err
    assert "thing" in err
    assert "error" in err.lower()


def test_missing_tag_lenient_warns(tmp_path: Path, capsys) -> None:
    """Default (no --strict) lets DEV image builds complete despite an
    unresolvable entry, but the warning must surface in stderr so a
    careless release dispatch is still visible to whoever reads logs.
    """
    manifest = _write_unresolvable_manifest(tmp_path)
    out_root = tmp_path / "out"

    fetch = _load_module()
    rc = fetch.main(["fetch_firmware.py", str(manifest), str(out_root)])

    assert rc == 0
    err = capsys.readouterr().err
    assert "thing" in err
    assert "warning" in err.lower()


def test_empty_firmware_section_is_ok(tmp_path: Path) -> None:
    """A manifest with no [firmware.*] entries succeeds in either mode.

    The gate applies to entries that exist but can't resolve, not to
    the absence of entries.
    """
    manifest = tmp_path / "manifest.toml"
    manifest.write_text("# no firmware section\n")
    out_root = tmp_path / "out"

    fetch = _load_module()
    assert fetch.main(["fetch_firmware.py", str(manifest), str(out_root)]) == 0
    assert (
        fetch.main(
            [
                "fetch_firmware.py",
                str(manifest),
                str(out_root),
                "--strict",
            ]
        )
        == 0
    )
