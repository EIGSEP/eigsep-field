<!--
If this PR is part of a coordinated change across siblings, keep the
Refs footer and the coordinated-change label. Otherwise delete the
coordinated-change section.
-->

## Summary

- _one-line description_

## Coordinated change

- Parent: (delete this line if single-repo) Refs: EIGSEP/eigsep-field#<n>
- Branch name: `field/<n>-<slug>`
- Label: `coordinated-change`
- Siblings with paired PRs: _list_

## Manifest impact

- [ ] No manifest changes
- [ ] Manifest bumped; `./scripts/refresh-lock.sh` run; `uv.lock` and `requirements.txt` committed

## Test plan

- [ ] `ruff check . && ruff format --check .`
- [ ] `pytest` green locally
- [ ] (if manifest changed) `python3 scripts/verify_manifest.py manifest.toml` passes
- [ ] (if manifest changed) `eigsep-field info` shows the expected blessed tuple
