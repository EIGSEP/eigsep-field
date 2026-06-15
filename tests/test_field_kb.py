"""Structure + invariant checks for the curated field-KB (docs/field-kb).

These guard the operator knowledge base: required files exist, the
glossary defines the load-bearing acronyms, and every runbook carries
the diagnostic section headings the operator agent relies on. Content
quality is the deliverable here, so the test encodes the contract.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
KB = REPO_ROOT / "docs" / "field-kb"


def test_corpus_ignore_excludes_blobs_keeps_docs():
    patterns = (KB / "anythingllm" / "corpus.ignore").read_text()
    # Big binaries must be excluded from a text RAG index.
    for pat in (".git/", ".venv/", "*.img", "*.npz", "__pycache__/"):
        assert pat in patterns, f"missing ignore pattern: {pat}"
    # But hardware PDFs/docx are shipped on purpose.
    assert "*.pdf" not in patterns
    assert "*.docx" not in patterns
