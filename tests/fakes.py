"""FakeBedrock: a `BedrockPort` that replays queued responses and records every call."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from botocore.exceptions import ClientError

FIXTURES = Path(__file__).parent / "fixtures" / "bedrock"


def fixture(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    return data


def client_error(code: str, operation: str = "Converse") -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": code}}, operation)


class FakeBedrock:
    def __init__(
        self, retrieve: list[Mapping[str, Any] | Exception], converse: list[Mapping[str, Any] | Exception] | None = None
    ) -> None:
        self._retrieve = list(retrieve)
        self._converse = list(converse or [])
        self.retrieve_calls: list[dict[str, Any]] = []
        self.converse_calls: list[Mapping[str, Any]] = []

    @staticmethod
    def _next(queue: list[Mapping[str, Any] | Exception]) -> Mapping[str, Any]:
        if not queue:
            raise AssertionError("FakeBedrock: unexpected call")
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def retrieve(
        self, *, knowledge_base_id: str, query: str, number_of_results: int, doc_type: str | None
    ) -> Mapping[str, Any]:
        self.retrieve_calls.append(
            {"knowledge_base_id": knowledge_base_id, "query": query, "n": number_of_results, "doc_type": doc_type}
        )
        return self._next(self._retrieve)

    def converse(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        self.converse_calls.append(request)
        return self._next(self._converse)
