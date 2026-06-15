# Field-KB corpus for an offline AnythingLLM operator agent — design

**Status:** approved design, ready for implementation plan
**Date:** 2026-06-15
**Owner:** Christian Hellum Bye

## Problem

We want an offline AI agent (AnythingLLM, or equivalent local RAG) running on a
**laptop** — not on the field Pis — that an operator can ask natural-language
troubleshooting questions during a deployment ("the SNAP shows no data, what do
I check?", "which Pi is the DHCP server?", "how do I reflash the Pico?"). It must
work with no internet, surveying our `src/` code (this repo + the field-stack
siblings) and our hardware documentation.

## Locked decisions

These were settled during brainstorming and drive the rest of the design:

1. **Primary purpose: operator troubleshooting.** Not dev onboarding. The corpus
   leans on runbooks, ICDs, role topology, and hardware notes; code is a
   supporting reference.
2. **Docs centralized in `eigsep-field`.** This repo is already the umbrella and
   owns `docs/operator` + `docs/interface` (the permalink index). The curated
   operator KB lives here in `docs/field-kb/`; siblings stay code-only.
3. **Corpus = curated maps + full `src/`.** Hand-written architecture/code-map
   markdown per repo, *plus* the entire `src/` trees of the field-stack siblings
   ingested raw, for maximum recall.
4. **The corpus is pinned to the blessed manifest tuple** (currently release
   `2026.4.0`), the same SHAs the image/wheelhouse and `docs/interface`
   permalinks are built from.
5. **Set up online, before deployment. Never refreshed in the field.** All docs
   and code are written before the trip; the laptop is provisioned with the
   corpus at the lab. There is no field-side refresh path.

## Corpus scope

In scope (the blessed field stack, from `manifest.toml`):

- `eigsep-field` (this repo)
- `eigsep_observing`, `eigsep_redis`, `pyvalon`
- `pico-firmware` / `picohost`
- `CMT-VNA` / `eigsep-vna`
- `casperfpga` (backend hardware driver)
- `eigsep_dac` (rfsoc bitstream loader — vendored reference)

Out of scope:

- Analysis/sim repos (`data-analysis`, `beam_models`, `hera_cal`, `eigsep_sims`, …).
- `eigsep-motor-control` and `eigsep_cal` — not in the blessed tuple.
  `eigsep-motor-control` is archived and **not referenced** by this stack: the
  only "motor" reference is the `motor` *sensor schema* in
  `docs/interface/sensor-schemas.md` (az/el telemetry flowing through
  `eigsep_observing`'s `SENSOR_SCHEMAS`, reported by the panda-side `picohost`).
  `panda_observe` drives actuators via pico-firmware, not the archived repo.
- `lgpio` (PyPI sdist, no git clone on the image) — no source tree to ingest.
- `cmtvna` (proprietary external binary) — no source.

## Core idea

AnythingLLM **is** the lookup index: it embeds documents into a local vector
store (LanceDB) and answers over them with a local LLM. It does naive chunking,
has no code/symbol awareness, no git awareness, and cites by source filename. So
the engineering work is not "build a search index" — it is:

1. **Feed it well-structured retrieval anchors** (glossary, FAQ, runbooks, code
   maps) so naive chunking and acronym-weak embedders still retrieve well.
2. **Assemble a clean, pinned corpus** reproducibly from the blessed tuple.

Two deliverables: a curated operator KB (markdown, in this repo) and a
corpus-build script (assembles KB + ICDs + full `src/` into an importable
folder).

## Directory layout

```
docs/field-kb/
  README.md              # map-of-content hub — the human "start here" / lookup index
  glossary.md            # acronyms & terms: SNAP, RFSoC, CMT-VNA, Pico, panda/backend,
                         #   casperfpga, Redis buses, correlator, chrony/RTC, DHCP, …
  faq.md                 # operator-phrased Q&A ("which Pi is the DHCP server?")
  topology.md            # role map, wiring, IPs, what-runs-where (lifted from CLAUDE.md)
  runbooks/              # symptom -> diagnosis -> fix, one self-contained file each
    no-correlator-data.md, pico-wont-flash.md, vna-not-found.md,
    dhcp-not-serving.md, service-wont-start.md, network-bringup.md, time-sync.md, …
  hardware/              # curated from the locked-up formats
    snap.md, rfsoc.md,
    cmt-vna.md           # curated from cmt_vna/docs/*.pdf vendor manuals
    pico.md              # curated from pico-firmware BNO080/085 datasheet
    correlator-notes.md  # converted from eigsep_corr/docs/*.docx
  codemaps/              # per-repo one-page architecture overview
    eigsep_observing.md, eigsep_redis.md, casperfpga.md, pico-firmware.md,
    cmt_vna.md, pyvalon.md, eigsep-field.md
  anythingllm/
    setup.md             # offline install on the laptop + recommended local model/embedder
    workspace-prompt.md  # operator-troubleshooting system prompt (incl. corpus-version note)
    refresh.md           # exact pre-deployment "rebuild + re-ingest" steps
    corpus.ignore        # exclude patterns (.venv, *.img, lockfiles, blobs, fixtures, …)

scripts/build-field-kb.py   # assembles the pinned corpus folder + stamps provenance
scripts/refresh-field-kb.sh # online, pre-deployment: fetch release corpus + push to local AnythingLLM
```

## Scaffolding, and why each piece earns its keep for RAG

| Piece | RAG rationale |
|---|---|
| **Glossary** | Embedders are weak on acronyms; one anchored definition per term disambiguates every downstream query mentioning it. Highest leverage per word. |
| **FAQ** (operator-phrased) | RAG retrieves by similarity to the *question*. Docs written as the questions operators ask keyword-match far better than reference prose. |
| **README / MOC hub** | Human "lookup index" and a high-recall hub doc tying the corpus together. |
| **Topology / role map** | The single most-asked fact (which Pi runs what / what IP). Already prose in `CLAUDE.md` — promote to an operator-facing doc. |
| **Runbooks** | Symptom->fix is exactly the troubleshooting query shape; self-contained so a chunk retrieves cleanly. |
| **Hardware notes** | Vendor PDFs + `.docx` correlator notes are real knowledge currently un-retrievable in those formats — convert + curate to markdown. |
| **Code maps** | Naive chunking shreds raw code context; a one-page "what this repo does / entry points" gives the agent scaffolding to make raw `src/` chunks meaningful. |
| **Provenance stamp** | `CORPUS-MANIFEST.md` (release + per-repo SHAs + build date) so the agent can state which release the corpus matches. |

Existing `docs/interface/*` (ICDs) and `docs/operator/*` are ingested as-is — no
duplication.

## Corpus assembly — `build-field-kb.py`

Runs on the build machine (CI or a dev box with siblings checked out at blessed
SHAs, like the wheelhouse build). It:

1. Copies `docs/field-kb/**`, `docs/interface/**`, `docs/operator/**`.
2. Copies the field-stack `src/` trees at their `manifest.toml` SHAs, minus
   `corpus.ignore` (excludes `.venv`, `*.img`, lockfiles, binary blobs, test
   fixtures, `node_modules`, …).
3. Hardware notes: ships the CMT vendor PDFs directly (AnythingLLM extracts
   their text on ingest) and converts the `eigsep_corr` `.docx` notes to
   markdown, alongside the hand-curated `hardware/*.md` summaries.
4. Writes `CORPUS-MANIFEST.md` (release version, per-repo SHAs, build date).
5. Emits a single folder ready to import into AnythingLLM.

Flags:

- default: build from the blessed manifest SHAs (release corpus).
- `--from-worktree`: build from local sibling checkouts — for fast iteration
  while *authoring* the docs online, pre-deployment. Not a field path.

## CI automation — `field-kb.yml`

The **build + publish half is fully automatic**; nothing to remember. A new
workflow triggered on the same `v*` release tag as `image.yml`:

- checkout → clone field-stack siblings at blessed SHAs (as the wheelhouse build
  already does) → run `build-field-kb.py` → package
  `field-kb-corpus-<version>.tar.gz`.
- reuse `image.yml`'s blessed-vs-DEV ref logic: only an exact `v{release}` match
  attaches the artifact to the GitHub Release; everything else is a DEV artifact.

The **ingest half is inherently local and operator-initiated** — AnythingLLM
lives on the laptop and GitHub cannot push into it. Per locked decision 5 this is
done **online, at the lab, before deployment**, never in the field.

## Refresh / regeneration model

AnythingLLM holds a point-in-time snapshot; it does not auto-pick-up code, docs,
or releases. Regeneration is an explicit rebuild + re-ingest, done **only online,
pre-deployment**:

- `scripts/refresh-field-kb.sh` (online-only): `gh release download` the latest
  corpus artifact → push into the local AnythingLLM via its developer API (drop
  the previous snapshot, embed the new one). One command.

**Field hot-patches do not invalidate the corpus.** Field bug-fixes are
structure-preserving and not user-facing (a load-bearing assumption recorded
here): the operator KB describes blessed-release structure and behavior, which
hot-patches do not move. Hence no field refresh is required for the duration of a
campaign.

**Don't-forget mechanisms** (setup is a deliberate pre-trip step, so these guard
the one manual action):

1. CI builds + publishes the corpus on every release tag — the hard part can't be
   forgotten.
2. A checklist line in `.github/ISSUE_TEMPLATE/release-coordination.yml`:
   "Refresh the field-KB corpus on the laptop: `scripts/refresh-field-kb.sh` —
   see `docs/field-kb/anythingllm/refresh.md`" (next to the existing website-tag
   bump line).
3. A step in `docs/operator/laptop.md` pre-deployment bring-up.
4. The agent states its corpus version in answers (`CORPUS-MANIFEST.md` pinned
   into `workspace-prompt.md`), so a mismatch with the deployed release is
   self-evident.

## AnythingLLM configuration

- **Fully local stack** for offline use: AnythingLLM (Desktop app on Linux) +
  Ollama for the LLM + embedder, LanceDB vector store.
- **Recommended starting point (not locked in):** LLM = `qwen2.5:7b-instruct`
  via Ollama (CPU / 16 GB-class sweet spot, strong at grounded cite-the-doc
  answering; try 14B on a 32 GB+ / GPU laptop); embedder = `nomic-embed-text`
  via Ollama (built-in `all-MiniLM` as zero-dependency fallback). The final pick
  is chosen during a Phase-1 model bake-off — models hot-swap in AnythingLLM
  without rebuilding the corpus, so deferring costs nothing.
- **Two target laptops, both Linux:** the primary ThinkPad and a separate Ubuntu
  laptop. `setup.md` is an operator-runnable Linux install guide (the operator
  performs the Ollama install and model pulls). Confirm each laptop's RAM/GPU to
  finalize the model size.
- **Workspace system prompt** (`workspace-prompt.md`): operator-troubleshooting
  persona — cite the source doc, say plainly when unsure, prefer runbooks, and
  state the corpus release version.
- **`corpus.ignore`** keeps the index clean (no 10 GB `.img` files, no `.venv`,
  no lockfiles/fixtures).

## Phasing

**MVP first, prove the retrieval loop on the laptop, then fill in:**

- **Phase 1 (MVP):** `topology.md` + `glossary.md` + 3–4 highest-value runbooks +
  `build-field-kb.py` + AnythingLLM `setup.md` and `workspace-prompt.md`. Install
  the stack on both Linux laptops, run a short **model bake-off** (Qwen2.5-7B vs.
  a larger model if RAM allows) against real operator questions, and settle the
  default LLM/embedder.
- **Phase 2:** code maps for each field-stack repo; convert + curate the hardware
  notes (PDF/docx); FAQ; remaining runbooks.
- **Phase 3:** `field-kb.yml` CI automation + `refresh-field-kb.sh` + the
  release-checklist / laptop-runbook prompts.

## Out of scope (YAGNI)

- No custom vector DB or embedding pipeline — AnythingLLM owns that.
- No symbol-level code index — curated maps + full `src/` suffice for operator
  troubleshooting.
- No auto-generated runbooks — hand-written.
- No field-side / offline / mid-campaign refresh — decision 5.
- Analysis/sim repos, motor-control, `eigsep_cal` — out of corpus.

## Open questions / follow-ups

- Final local LLM + embedder choice — deferred to a Phase-1 bake-off on the
  actual laptops. Default starting point: `qwen2.5:7b-instruct` +
  `nomic-embed-text`. Confirm each laptop's RAM/GPU to settle the model size.

Resolved during review:

- **CMT vendor PDFs are shipped** in the corpus artifact (decided 2026-06-15) —
  no local-staging carve-out needed.
