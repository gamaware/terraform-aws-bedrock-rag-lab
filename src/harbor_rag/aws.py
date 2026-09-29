"""Production `BedrockPort`: boto3 clients for bedrock-agent-runtime (Retrieve) and bedrock-runtime (Converse).

botocore retries are off (one attempt) because `service.call_with_retries` owns the retry policy; two retry layers
would multiply the attempts and hide throttling from the metrics.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, cast

import boto3
from botocore.config import Config

if TYPE_CHECKING:
    from mypy_boto3_bedrock_agent_runtime import AgentsforBedrockRuntimeClient
    from mypy_boto3_bedrock_runtime import BedrockRuntimeClient

CLIENT_CONFIG = Config(retries={"max_attempts": 1, "mode": "standard"}, connect_timeout=3, read_timeout=30)


class Boto3Bedrock:
    def __init__(
        self,
        agent_runtime: AgentsforBedrockRuntimeClient | None = None,
        runtime: BedrockRuntimeClient | None = None,
    ) -> None:
        self._agent_runtime = agent_runtime or boto3.client("bedrock-agent-runtime", config=CLIENT_CONFIG)
        self._runtime = runtime or boto3.client("bedrock-runtime", config=CLIENT_CONFIG)

    def retrieve(
        self, *, knowledge_base_id: str, query: str, number_of_results: int, doc_type: str | None
    ) -> Mapping[str, Any]:
        vector_config: dict[str, Any] = {"numberOfResults": number_of_results}
        if doc_type:
            vector_config["filter"] = {"equals": {"key": "doc_type", "value": doc_type}}
        response = self._agent_runtime.retrieve(
            knowledgeBaseId=knowledge_base_id,
            retrievalQuery={"text": query},
            retrievalConfiguration={"vectorSearchConfiguration": cast(Any, vector_config)},
        )
        return cast(Mapping[str, Any], response)

    def converse(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        return cast(Mapping[str, Any], self._runtime.converse(**cast(Any, request)))
