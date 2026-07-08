"""Drift guards: the sync-image file map must mirror the image stage.

The image build (00-run.sh) and `eigsep-field sync-image` (_sync.py)
both stage the files/ tree. These tests fail CI when a file is added
to the stage without teaching the sync map about it, and when
tombstones contradict the live map.
"""

from __future__ import annotations

from pathlib import Path

from eigsep_field import _sync

REPO = Path(__file__).resolve().parent.parent
FILES = _sync.files_dir(REPO)

# Build-time-only inputs the sync map intentionally does not stage.
EXCLUDED = {
    "_chroot-install.sh",  # runs only inside the pi-gen chroot
    "apt-packages.txt",  # consumed by the apt step, not file-copied
    "wheels",  # image-build output; may exist in a dev tree
    "firmware",  # image-build output; may exist in a dev tree
    "eigsep-field-src",  # image-build output; may exist in a dev tree
}


def test_every_staged_file_is_mapped_or_excluded():
    mapped = {p for _, p in _sync.iter_map_files(REPO)}
    unmapped = []
    for p in FILES.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(FILES)
        if rel.parts[0] in EXCLUDED or rel.name in EXCLUDED:
            continue
        if p not in mapped:
            unmapped.append(str(rel))
    assert not unmapped, (
        "files staged by the image but unknown to sync-image "
        f"(add to _sync.FILE_MAP or EXCLUDED): {unmapped}"
    )


def test_map_sources_all_exist():
    # iter_map_files raises FileNotFoundError on a missing non-glob
    pairs = _sync.iter_map_files(REPO)
    assert pairs


def test_tombstones_do_not_collide_with_map():
    import tomllib

    manifest = tomllib.loads((REPO / "manifest.toml").read_text())
    ctx = _sync.SyncContext(tree=REPO, manifest=manifest)
    dests = {
        str(_sync.dest_path(ctx, e, s)) for e, s in _sync.iter_map_files(REPO)
    }
    for tomb in _sync.read_removed_paths(REPO):
        assert tomb not in dests, (
            f"{tomb} is tombstoned AND still installed by the map"
        )


def test_apt_packages_file_parses_nonempty():
    pkgs = _sync.read_apt_packages(REPO)
    assert "python3" in pkgs
    assert all(" " not in p for p in pkgs)


def test_removed_paths_are_absolute():
    for tomb in _sync.read_removed_paths(REPO):
        assert tomb.startswith("/"), tomb
