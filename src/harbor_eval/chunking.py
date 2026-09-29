"""Local re-implementations of the Bedrock Knowledge Bases chunking strategies, for the offline comparison.

Tokens are approximated by whitespace-separated words. `search_text` is what gets embedded and searched; `text` is
what a `Retrieve` call returns. They differ only for hierarchical chunking, which searches the small child chunks and
returns their parent.
"""

from __future__ import annotations

from dataclasses import dataclass

from harbor_eval.corpus import Document


@dataclass(frozen=True)
class Strategy:
    name: str
    kind: str  # fixed | hierarchical | none
    max_tokens: int = 0
    overlap: float = 0.0
    child_tokens: int = 0
    note: str = ""


STRATEGIES = {
    s.name: s
    for s in (
        Strategy("fixed-300", "fixed", 300, 0.2, note="Bedrock default (300 tokens, 20 percent overlap)"),
        Strategy("fixed-200", "fixed", 200, 0.2, note="medium fixed chunks"),
        Strategy("fixed-100", "fixed", 100, 0.2, note="small fixed chunks"),
        Strategy("hierarchical-300-60", "hierarchical", 300, 0.0, 60, note="search 60-token children, return parent"),
        Strategy("none", "none", note="one chunk per document"),
    )
}


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    doc: Document
    text: str
    search_text: str


def _windows(words: list[str], size: int, overlap: float) -> list[list[str]]:
    if len(words) <= size:
        return [words]
    step = max(1, int(size * (1 - overlap)))
    windows = []
    for start in range(0, len(words), step):
        windows.append(words[start : start + size])
        if start + size >= len(words):
            break
    return windows


def chunk(doc: Document, strategy: Strategy) -> list[Chunk]:
    words = doc.text.split()
    if strategy.kind == "none":
        return [Chunk(f"{doc.doc_id}#0", doc, doc.text, doc.text)]
    if strategy.kind == "fixed":
        return [
            Chunk(f"{doc.doc_id}#{i}", doc, " ".join(w), " ".join(w))
            for i, w in enumerate(_windows(words, strategy.max_tokens, strategy.overlap))
        ]
    chunks = []
    for p, parent in enumerate(_windows(words, strategy.max_tokens, strategy.overlap)):
        parent_text = " ".join(parent)
        for c, child in enumerate(_windows(parent, strategy.child_tokens, 0.0)):
            chunks.append(Chunk(f"{doc.doc_id}#{p}.{c}", doc, parent_text, " ".join(child)))
    return chunks


def chunk_corpus(docs: list[Document], strategy: Strategy) -> list[Chunk]:
    return [c for d in docs for c in chunk(d, strategy)]
