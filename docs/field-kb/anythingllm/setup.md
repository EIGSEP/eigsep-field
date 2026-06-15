# Setting up the offline operator agent (Linux laptop)

Do this **online, before the deployment**, on each laptop (the primary
ThinkPad and the spare Ubuntu laptop). Once set up, the agent runs fully
offline in the field.

## 1. Install Ollama (the local model runtime)

    curl -fsSL https://ollama.com/install.sh | sh
    systemctl --user enable --now ollama   # or: ollama serve &

## 2. Pull the models

    ollama pull qwen2.5:7b-instruct   # the LLM (default starting point)
    ollama pull nomic-embed-text      # the embedder

On a 32 GB+ / GPU laptop you may also pull a larger model to compare in
the bake-off, e.g. `ollama pull qwen2.5:14b-instruct`.

## 3. Install AnythingLLM Desktop

Download the Linux AppImage from https://anythingllm.com/desktop, make
it executable, and run it:

    chmod +x AnythingLLM-*.AppImage
    ./AnythingLLM-*.AppImage

## 4. Point AnythingLLM at the local stack

In AnythingLLM settings:
- **LLM Preference:** Ollama → base URL `http://127.0.0.1:11434` → model
  `qwen2.5:7b-instruct`.
- **Embedding Preference:** Ollama → `nomic-embed-text` (or the built-in
  AnythingLLM embedder as a zero-dependency fallback).
- **Vector Database:** the built-in LanceDB (default).

## 5. Build and import the corpus

On a machine with the field-stack siblings checked out next to this repo:

    python scripts/build-field-kb.py --out ./out/field-kb-corpus

Copy `out/field-kb-corpus/` to the laptop, then in AnythingLLM:
- Create a workspace named `eigsep-field`.
- Upload the corpus folder's files (drag the folder into the workspace's
  document upload), then **Save and Embed**.
- Open `CORPUS-MANIFEST.md` from the corpus and note the release version.

## 6. Set the workspace prompt

Paste the contents of `workspace-prompt.md` into the workspace's
**System Prompt** (Workspace Settings → Chat). Fill the corpus release
version into the prompt where indicated.

## 7. Choose the model

Run the question set in `bakeoff.md` against each candidate model and
keep the best. Models hot-swap in AnythingLLM (step 4) without
rebuilding the corpus.
