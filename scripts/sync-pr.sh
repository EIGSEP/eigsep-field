#!/usr/bin/env bash
# Open a coordinated PR branch in every EIGSEP sibling repo.
#
#   ./scripts/sync-pr.sh <issue-number> <slug> [repo ...]
#
# Default repo set is all five Python siblings. Each gets:
#   - branch: field/<issue>-<slug>
#   - empty commit referencing this repo's issue
#   - draft PR labelled 'coordinated-change' with a 'Refs:' footer
set -euo pipefail

ISSUE=${1:?usage: sync-pr.sh <issue-number> <slug> [repo ...]}
SLUG=${2:?usage: sync-pr.sh <issue-number> <slug> [repo ...]}
shift 2

REPOS=("$@")
if [[ ${#REPOS[@]} -eq 0 ]]; then
    REPOS=(eigsep_redis pico-firmware cmt_vna eigsep_observing pyvalon)
fi

BRANCH="field/${ISSUE}-${SLUG}"
ROOT=$(mktemp -d -t sync-pr-XXXX)
trap "rm -rf $ROOT" EXIT

for repo in "${REPOS[@]}"; do
    echo "=== $repo ==="
    gh repo clone "EIGSEP/$repo" "$ROOT/$repo" -- --depth=50 --quiet
    git -C "$ROOT/$repo" checkout -b "$BRANCH"
    git -C "$ROOT/$repo" commit --allow-empty -m "chore: coordinated change for eigsep-field#${ISSUE}

Refs: EIGSEP/eigsep-field#${ISSUE}"
    git -C "$ROOT/$repo" push -u origin "$BRANCH"
    gh pr create --repo "EIGSEP/$repo" \
        --title "[field#${ISSUE}] ${SLUG}" \
        --body "Part of EIGSEP/eigsep-field#${ISSUE}

Refs: EIGSEP/eigsep-field#${ISSUE}" \
        --label "coordinated-change" \
        --draft
done

echo
echo "done. draft PRs opened on branch $BRANCH in: ${REPOS[*]}"
