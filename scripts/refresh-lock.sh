#!/usr/bin/env bash
# Regenerate uv.lock and exported requirements.txt from manifest.toml.
# Run after editing manifest.toml or any dep in pyproject.toml.
set -euo pipefail

cd "$(dirname "$0")/.."

if ! command -v uv >/dev/null 2>&1; then
    echo "uv is required (see https://docs.astral.sh/uv/)" >&2
    exit 2
fi

uv lock
uv export --format requirements-txt --no-hashes \
    --output-file requirements.txt
uv export --format requirements-txt --output-file requirements-hashed.txt

echo "updated uv.lock, requirements.txt, requirements-hashed.txt"
