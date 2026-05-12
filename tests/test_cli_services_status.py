"""Regression: `eigsep-field services status <name>` must stream to the
terminal, not swallow systemctl's output.

Earlier the branch called the ``systemctl()`` helper (which captures
stdout/stderr) and discarded the captured message, so the operator saw
nothing. The fix is to shell out directly with no ``capture_output``.
"""

from __future__ import annotations

import subprocess
from types import SimpleNamespace


def test_services_status_streams_to_terminal(monkeypatch):
    from eigsep_field import cli

    seen: list[tuple[tuple, dict]] = []

    def fake_run(argv, *args, **kwargs):
        seen.append((tuple(argv), dict(kwargs)))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    rc = cli.main(["services", "status", "redis"])

    assert rc == 0
    assert len(seen) == 1, f"expected one subprocess.run call, got {seen}"
    argv, kwargs = seen[0]
    assert argv == (
        "systemctl",
        "status",
        "redis-server.service",
        "--no-pager",
    )
    # The regression: if output is captured here, the operator sees
    # nothing on the terminal. Streaming = no capture_output kwarg
    # (and no stdout/stderr piping).
    assert kwargs.get("capture_output") is not True
    assert "stdout" not in kwargs
    assert "stderr" not in kwargs
