"""An offline `BedrockPort`: the local retriever for `Retrieve` and an extractive stand-in for `Converse`.

The stand-in model picks the source sentence that shares the most terms with the question and cites it, or answers
NO_ANSWER when nothing overlaps enough. It is not a language model; it exists so the production answering code
(`harbor_rag.service.answer_question`) runs end to end over the golden set without a model call. Answer quality
numbers from it measure the pipeline (selection, citation mapping, refusals), not generation quality; the `--live`
run measures that.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from harbor_eval.embeddings import local_embed
from harbor_eval.retriever import LocalRetriever
from harbor_eval.text import terms
from harbor_rag.prompt import NO_ANSWER, SYSTEM_PROMPT, estimate_tokens

SOURCE_HEADER = re.compile(r"^\[(\d+)\] .*$", re.MULTILINE)
MIN_OVERLAP = 2


def _sources(request: Mapping[str, Any]) -> tuple[str, dict[int, str]]:
    question, context = "", ""
    for block in request["messages"][0]["content"]:
        guard = block.get("guardContent", {}).get("text", {})
        if "grounding_source" in guard.get("qualifiers", []):
            context = guard["text"]
        elif "query" in guard.get("qualifiers", []):
            question = guard["text"]
    headers = list(SOURCE_HEADER.finditer(context))
    sources = {}
    for i, header in enumerate(headers):
        end = headers[i + 1].start() if i + 1 < len(headers) else len(context)
        sources[int(header.group(1))] = context[header.end() : end]
    return question, sources


def extractive_answer(request: Mapping[str, Any]) -> dict[str, Any]:
    question, sources = _sources(request)
    wanted = set(terms(question))
    best: tuple[int, int, str] = (0, 0, "")
    for index, text in sources.items():
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", text):
            sentence = sentence.strip(" -*#|")
            overlap = len(wanted & set(terms(sentence)))
            if overlap > best[0]:
                best = (overlap, index, sentence)
    answer = f"{best[2]} [{best[1]}]" if best[0] >= MIN_OVERLAP else NO_ANSWER
    prompt_chars = len(SYSTEM_PROMPT) + len(question) + sum(len(t) for t in sources.values())
    return {
        "output": {"message": {"role": "assistant", "content": [{"text": answer}]}},
        "stopReason": "end_turn",
        "usage": {
            "inputTokens": estimate_tokens("x" * prompt_chars),
            "outputTokens": estimate_tokens(answer),
            "totalTokens": estimate_tokens("x" * prompt_chars) + estimate_tokens(answer),
        },
    }


class LocalBedrock:
    def __init__(self, retriever: LocalRetriever, query_vectors: Mapping[str, list[float]]) -> None:
        self.retriever = retriever
        self.query_vectors = query_vectors
        self.converse_calls = 0

    def retrieve(
        self, *, knowledge_base_id: str, query: str, number_of_results: int, doc_type: str | None
    ) -> Mapping[str, Any]:
        vector = self.query_vectors.get(query) or local_embed(query)
        return self.retriever.retrieve(query, vector, number_of_results, doc_type)

    def converse(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        self.converse_calls += 1
        return extractive_answer(request)
