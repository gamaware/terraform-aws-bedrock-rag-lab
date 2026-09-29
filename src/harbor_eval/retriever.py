"""A local stand-in for the knowledge base's `Retrieve` call.

Scores combine BM25 over the chunk text with cosine similarity of the fixture embeddings, both on a 0 to 1 scale, so
the absolute `min_score` cut-off in the ask function means something offline too. Results have the `Retrieve`
response shape, so `harbor_rag.prompt.select_sources` runs on them unchanged.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping
from typing import Any

from harbor_eval.chunking import Chunk
from harbor_eval.embeddings import cosine
from harbor_eval.text import terms

K1 = 1.2
B = 0.75
BM25_HALF = 6.0  # BM25 score that maps to 0.5 on the saturating 0..1 scale


class LocalRetriever:
    def __init__(self, chunks: list[Chunk], chunk_vectors: Mapping[str, list[float]], mode: str = "hybrid") -> None:
        if mode not in ("hybrid", "lexical", "vector"):
            raise ValueError(mode)
        self.chunks = chunks
        self.vectors = chunk_vectors
        self.mode = mode
        self.tfs = [Counter(terms(c.search_text)) for c in chunks]
        self.lengths = [sum(tf.values()) for tf in self.tfs]
        self.avg_len = sum(self.lengths) / max(1, len(self.lengths))
        df: Counter[str] = Counter()
        for tf in self.tfs:
            df.update(tf.keys())
        n = len(chunks)
        self.idf = {t: math.log(1 + (n - d + 0.5) / (d + 0.5)) for t, d in df.items()}

    def _bm25(self, query_terms: list[str], i: int) -> float:
        tf, length = self.tfs[i], self.lengths[i]
        score = 0.0
        for term in query_terms:
            f = tf.get(term, 0)
            if f:
                score += self.idf[term] * f * (K1 + 1) / (f + K1 * (1 - B + B * length / self.avg_len))
        return score

    def score(self, query: str, query_vector: list[float], i: int) -> float:
        lexical = self._bm25(terms(query), i)
        lexical = lexical / (lexical + BM25_HALF)
        vector = max(0.0, cosine(query_vector, self.vectors[self.chunks[i].chunk_id]))
        if self.mode == "lexical":
            return lexical
        if self.mode == "vector":
            return vector
        return 0.5 * lexical + 0.5 * vector

    def retrieve(
        self, query: str, query_vector: list[float], number_of_results: int, doc_type: str | None = None
    ) -> dict[str, Any]:
        scored = [
            (self.score(query, query_vector, i), c)
            for i, c in enumerate(self.chunks)
            if doc_type is None or c.doc.doc_type == doc_type
        ]
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return {
            "retrievalResults": [
                {
                    "content": {"type": "TEXT", "text": c.text},
                    "location": {"type": "S3", "s3Location": {"uri": c.doc.uri}},
                    "score": round(s, 4),
                    "metadata": {
                        "x-amz-bedrock-kb-source-uri": c.doc.uri,
                        "x-amz-bedrock-kb-chunk-id": c.chunk_id,
                        "doc_type": c.doc.doc_type,
                        "title": c.doc.title,
                        "doc_id": c.doc.doc_id,
                    },
                }
                for s, c in scored[:number_of_results]
            ]
        }
