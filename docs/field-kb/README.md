# EIGSEP field knowledge base

This is the operator knowledge base for the EIGSEP field stack — the
content fed to the offline AnythingLLM troubleshooting agent on the
field laptop. It is written for an operator standing at the
deployment, not for developers.

## Start here

- **[topology.md](topology.md)** — which Pi runs what, how things are
  wired, the LAN addresses. Read this first when something is "not
  responding".
- **[glossary.md](glossary.md)** — what every acronym means
  (SNAP, RFSoC, CMT-VNA, panda/backend, …).

## Runbooks (symptom → fix)

See [runbooks/](runbooks/):

- [No correlator data](runbooks/no-correlator-data.md) — backend Pi / SNAP.
- [DHCP not serving](runbooks/dhcp-not-serving.md) — backend Pi / LAN.
- [Pico won't flash](runbooks/pico-wont-flash.md) — panda Pi / Pico.
- [VNA not found](runbooks/vna-not-found.md) — panda Pi / CMT-VNA.

## Running the agent

- [anythingllm/setup.md](anythingllm/setup.md) — install Ollama +
  AnythingLLM on the laptop and import this corpus.
- [anythingllm/workspace-prompt.md](anythingllm/workspace-prompt.md) —
  the system prompt to paste into the workspace.
- [anythingllm/bakeoff.md](anythingllm/bakeoff.md) — the question set
  for choosing the local model.

## How this corpus is built

`scripts/build-field-kb.py` assembles this KB plus the interface ICDs
(`docs/interface/`), the operator runbooks (`docs/operator/`), and the
source trees of the blessed field-stack siblings into a single folder
to import into AnythingLLM. The corpus is pinned to the manifest
release; see the generated `CORPUS-MANIFEST.md` inside any built corpus
for the exact version and per-repo commits.
