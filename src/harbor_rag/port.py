"""The boundary between the answering logic and Amazon Bedrock.

`BedrockPort` takes and returns the request and response shapes of the Bedrock `Retrieve` and `Converse` APIs as
plain mappings. The production adapter (`harbor_rag.aws.Boto3Bedrock`) passes them to boto3 unchanged; tests and the
offline evaluation use fakes that return the same shapes, so the service code never knows which one it talks to.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol


class BedrockPort(Protocol):
    def retrieve(
        self, *, knowledge_base_id: str, query: str, number_of_results: int, doc_type: str | None
    ) -> Mapping[str, Any]:
        """Return a `Retrieve` response: {"retrievalResults": [{"content", "location", "score", "metadata"}]}."""
        ...

    def converse(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        """Send a `Converse` request and return its response."""
        ...
