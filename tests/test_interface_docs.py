"""Drift guard: every generated section in docs/interface/*.md must
match what ``scripts/gen_interface_docs.py`` would produce right now.

If this test fails, the fix is almost always:

    ./scripts/gen_interface_docs.py

...and commit the updated docs alongside whatever code change caused
the drift (e.g. a new ``SENSOR_SCHEMAS`` field, a new key constant).

Skipped if the authoritative sibling packages aren't installed — CI
always installs them at the manifest-pinned versions, so drift is
caught there even if local devs don't have the full stack.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "scripts"


def _load_generator():
    pytest.importorskip("eigsep_redis")
    pytest.importorskip("eigsep_observing")
    sys.path.insert(0, str(SCRIPTS))
    try:
        import gen_interface_docs

        return gen_interface_docs
    finally:
        if str(SCRIPTS) in sys.path:
            sys.path.remove(str(SCRIPTS))


def test_generated_sections_match_committed_docs():
    """Every doc with BEGIN/END markers must match fresh generator output."""
    gen = _load_generator()
    updated = gen.render_all(REPO_ROOT)
    drifted: list[str] = []
    for rel, new in updated.items():
        path = REPO_ROOT / rel
        current = path.read_text()
        if current != new:
            drifted.append(rel)
    assert not drifted, (
        "interface docs drifted from authoritative sources:\n"
        + "\n".join(f"  - {d}" for d in drifted)
        + "\n\nRun ./scripts/gen_interface_docs.py and commit the result."
    )


def test_generator_runs_in_check_mode():
    """`--check` returns 0 when docs are in sync (smoke of the CLI path)."""
    gen = _load_generator()
    rc = gen.main(["gen_interface_docs.py", "--check"])
    assert rc == 0
