"""The golden set in data/golden.jsonl: questions, the documents that answer them, and phrases a correct answer
contains. Questions with no relevant document must be refused."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from harbor_eval import DATA

GOLDEN = DATA / "golden.jsonl"


@dataclass(frozen=True)
class GoldenQuestion:
    qid: str
    question: str
    relevant: tuple[str, ...]
    must_include: tuple[str, ...]

    @property
    def answerable(self) -> bool:
        return bool(self.relevant)


def load_golden(path: Path = GOLDEN) -> list[GoldenQuestion]:
    questions = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            questions.append(
                GoldenQuestion(row["id"], row["question"], tuple(row["relevant"]), tuple(row["must_include"]))
            )
    return questions
