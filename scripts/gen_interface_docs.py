"""Regenerate tables in docs/interface/*.md from authoritative sources.

Imports ``eigsep_redis`` and ``eigsep_observing`` at runtime — those
siblings must be installed (e.g. via ``pip install -e ../eigsep_redis``
or from the blessed wheelhouse). The generator walks the authoritative
modules and rewrites any content between BEGIN/END markers in the
markdown files:

    <!-- BEGIN GENERATED: <section-id> -->
    <!-- END GENERATED: <section-id> -->

The test ``tests/test_interface_docs.py`` re-runs generation in memory
and diffs against the committed files; CI enforces zero drift. After
editing ``SENSOR_SCHEMAS`` or a ``keys.py``, run this script and commit
the updated docs alongside the code change.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


REDUCTION = {
    float: "float → mean of non-error survivors",
    int: "int → min of non-error survivors (expected invariant)",
    bool: "bool → any of non-error survivors",
    str: "str → first if unanimous, else ``UNKNOWN``",
}


def _type_name(t: type) -> str:
    return getattr(t, "__name__", repr(t))


def _reduction_label(t: type) -> str:
    return REDUCTION.get(t, f"custom ({_type_name(t)})")


def _classify_key_kind(name: str) -> str:
    if name.endswith("_HASH"):
        return "hash"
    if name.endswith("_STREAM"):
        return "stream"
    if name.endswith("_STREAMS_SET") or name.endswith("_SET"):
        return "set"
    if name.endswith("_KEY"):
        return "singleton key"
    return "key"


def _module_string_constants(module) -> list[tuple[str, str, str]]:
    out: list[tuple[str, str, str]] = []
    for attr in sorted(vars(module)):
        if attr.startswith("_"):
            continue
        val = getattr(module, attr)
        if not isinstance(val, str):
            continue
        out.append((attr, val, _classify_key_kind(attr)))
    return out


def _render_keys_table(rows: list[tuple[str, str, str]]) -> str:
    lines = [
        "| Constant | Value | Kind |",
        "|---|---|---|",
    ]
    for name, value, kind in rows:
        lines.append(f"| `{name}` | `{value!r}` | {kind} |")
    return "\n".join(lines) + "\n"


def _render_schema_table(schema: dict) -> str:
    lines = [
        "| Field | Type | Reduction |",
        "|---|---|---|",
    ]
    for field, typ in schema.items():
        lines.append(
            f"| `{field}` | `{_type_name(typ)}` | {_reduction_label(typ)} |"
        )
    return "\n".join(lines) + "\n"


def _section(begin_id: str, body: str) -> str:
    return (
        f"<!-- BEGIN GENERATED: {begin_id} -->\n"
        f"<!-- Do not edit by hand. Regenerate with ./scripts/gen_interface_docs.py -->\n"
        f"{body.rstrip()}\n"
        f"<!-- END GENERATED: {begin_id} -->"
    )


def _replace_section(text: str, begin_id: str, body: str) -> str:
    pattern = re.compile(
        rf"<!-- BEGIN GENERATED: {re.escape(begin_id)} -->.*?"
        rf"<!-- END GENERATED: {re.escape(begin_id)} -->",
        re.DOTALL,
    )
    if not pattern.search(text):
        raise KeyError(
            f"marker pair 'BEGIN/END GENERATED: {begin_id}' not found in doc"
        )
    return pattern.sub(_section(begin_id, body), text)


def _build_sensor_schemas_body() -> str:
    from eigsep_observing.io import (
        SENSOR_SCHEMAS,
        VNA_S11_CAL_KEYS,
        VNA_S11_HEADER_SCHEMA,
        VNA_S11_MODE_DATA_KEYS,
    )

    # Group sensors that share a schema object so we render the table once.
    by_identity: dict[int, tuple[list[str], dict]] = {}
    for name, schema in SENSOR_SCHEMAS.items():
        key = id(schema)
        by_identity.setdefault(key, ([], schema))[0].append(name)

    out: list[str] = []
    for names, schema in by_identity.values():
        names_md = ", ".join(f"`{n}`" for n in names)
        out.append(f"### {names_md}\n")
        if len(names) > 1:
            out.append(
                "Shared schema object — every listed sensor uses exactly "
                "the same fields.\n"
            )
        out.append(_render_schema_table(schema))
        out.append("")

    out.append("### VNA S11 header (`VNA_S11_HEADER_SCHEMA`)\n")
    out.append(
        "Published alongside each VNA measurement. `freqs` (numpy array) "
        "is validated separately from these scalar fields.\n"
    )
    out.append(_render_schema_table(VNA_S11_HEADER_SCHEMA))
    out.append("")

    out.append("### VNA S11 structural keys\n")
    out.append("| Constant | Members |")
    out.append("|---|---|")
    cal_list = ", ".join(f"`{k}`" for k in sorted(VNA_S11_CAL_KEYS))
    out.append(f"| `VNA_S11_CAL_KEYS` | {cal_list} |")
    for mode in sorted(VNA_S11_MODE_DATA_KEYS):
        members = ", ".join(
            f"`{k}`" for k in sorted(VNA_S11_MODE_DATA_KEYS[mode])
        )
        out.append(f"| `VNA_S11_MODE_DATA_KEYS['{mode}']` | {members} |")
    out.append("")

    return "\n".join(out)


def _build_redis_keys_body() -> str:
    import eigsep_observing.keys as obs_keys
    import eigsep_redis.keys as redis_keys

    out: list[str] = []
    out.append("#### `eigsep_redis` (transport layer)\n")
    out.append(_render_keys_table(_module_string_constants(redis_keys)))
    out.append("")
    out.append("#### `eigsep_observing` (observer side)\n")
    out.append(_render_keys_table(_module_string_constants(obs_keys)))
    return "\n".join(out)


GENERATORS = {
    "sensor-schemas": _build_sensor_schemas_body,
    "redis-keys": _build_redis_keys_body,
}

DOC_FILES = {
    "sensor-schemas": "docs/interface/sensor-schemas.md",
    "redis-keys": "docs/interface/redis-keys.md",
}


def render_all(repo_root: Path) -> dict[str, str]:
    """Return {doc_path: new_content} without writing to disk."""
    out: dict[str, str] = {}
    for section_id, build in GENERATORS.items():
        rel = DOC_FILES[section_id]
        path = repo_root / rel
        text = path.read_text()
        out[rel] = _replace_section(text, section_id, build())
    return out


def main(argv: list[str]) -> int:
    repo_root = Path(__file__).resolve().parent.parent
    check_only = "--check" in argv[1:]

    updated = render_all(repo_root)
    changed: list[str] = []
    for rel, new in updated.items():
        path = repo_root / rel
        if path.read_text() != new:
            changed.append(rel)
            if not check_only:
                path.write_text(new)

    if check_only:
        if changed:
            print("drift in:", file=sys.stderr)
            for c in changed:
                print(f"  - {c}", file=sys.stderr)
            return 1
        print("interface docs are in sync")
        return 0

    if changed:
        print("regenerated:")
        for c in changed:
            print(f"  - {c}")
    else:
        print("no changes")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
