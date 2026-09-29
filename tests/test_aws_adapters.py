"""The boto3 adapters send the right API parameters (botocore Stubber: no network, no credentials used)."""

from __future__ import annotations

import boto3
import pytest
from botocore.config import Config
from botocore.exceptions import ClientError
from botocore.stub import Stubber

from harbor_rag import ingest
from harbor_rag.aws import CLIENT_CONFIG, Boto3Bedrock
from tests.fakes import fixture


def test_botocore_retries_are_off() -> None:
    assert isinstance(CLIENT_CONFIG, Config)
    assert CLIENT_CONFIG.retries == {"max_attempts": 1, "mode": "standard"}


def test_retrieve_sends_the_doc_type_filter() -> None:
    agent_runtime = boto3.client("bedrock-agent-runtime", region_name="us-east-1")
    runtime = boto3.client("bedrock-runtime", region_name="us-east-1")
    with Stubber(agent_runtime) as stub:
        stub.add_response(
            "retrieve",
            fixture("retrieve_returns"),
            {
                "knowledgeBaseId": "KBHARBOR01",
                "retrievalQuery": {"text": "return window"},
                "retrievalConfiguration": {
                    "vectorSearchConfiguration": {
                        "numberOfResults": 8,
                        "filter": {"equals": {"key": "doc_type", "value": "returns"}},
                    }
                },
            },
        )
        port = Boto3Bedrock(agent_runtime, runtime)
        result = port.retrieve(
            knowledge_base_id="KBHARBOR01", query="return window", number_of_results=8, doc_type="returns"
        )
    assert len(result["retrievalResults"]) == 4


def test_retrieve_without_filter() -> None:
    agent_runtime = boto3.client("bedrock-agent-runtime", region_name="us-east-1")
    with Stubber(agent_runtime) as stub:
        stub.add_response(
            "retrieve",
            {"retrievalResults": []},
            {
                "knowledgeBaseId": "KBHARBOR01",
                "retrievalQuery": {"text": "q"},
                "retrievalConfiguration": {"vectorSearchConfiguration": {"numberOfResults": 5}},
            },
        )
        Boto3Bedrock(agent_runtime, boto3.client("bedrock-runtime", region_name="us-east-1")).retrieve(
            knowledge_base_id="KBHARBOR01", query="q", number_of_results=5, doc_type=None
        )


def test_converse_passes_the_request_through() -> None:
    runtime = boto3.client("bedrock-runtime", region_name="us-east-1")
    request = {
        "modelId": "m",
        "messages": [{"role": "user", "content": [{"text": "hi"}]}],
        "guardrailConfig": {"guardrailIdentifier": "g", "guardrailVersion": "1", "trace": "enabled"},
    }
    response = {k: v for k, v in fixture("converse_answer").items() if k != "trace"}
    with Stubber(runtime) as stub:
        stub.add_response("converse", response, request)
        out = Boto3Bedrock(boto3.client("bedrock-agent-runtime", region_name="us-east-1"), runtime).converse(request)
    assert out["stopReason"] == "end_turn"


S3_EVENT = {
    "id": "7bf73129-1428-4cd3-a780-95db273d1602",
    "detail-type": "Object Created",
    "source": "aws.s3",
    "detail": {"bucket": {"name": "harbor-goods-policies"}, "object": {"key": "returns/returns-standard-window.md"}},
}
ENV = {"KNOWLEDGE_BASE_ID": "KBHARBOR01", "DATA_SOURCE_ID": "DSHARBOR01"}


def test_ingestion_starts_with_an_idempotent_token() -> None:
    client = boto3.client("bedrock-agent", region_name="us-east-1")
    with Stubber(client) as stub:
        stub.add_response(
            "start_ingestion_job",
            {
                "ingestionJob": {
                    "knowledgeBaseId": "KBHARBOR01",
                    "dataSourceId": "DSHARBOR01",
                    "ingestionJobId": "JOB12345",
                    "status": "STARTING",
                    "startedAt": "2020-01-01T00:00:00Z",
                    "updatedAt": "2020-01-01T00:00:00Z",
                }
            },
            {
                "knowledgeBaseId": "KBHARBOR01",
                "dataSourceId": "DSHARBOR01",
                "clientToken": "s3-event-7bf73129-1428-4cd3-a780-95db273d1602",
                "description": "S3 change: returns/returns-standard-window.md",
            },
        )
        result = ingest.start_ingestion(S3_EVENT, client, ENV)
    assert result["job_id"] == "JOB12345"


def test_ingestion_conflict_is_raised_so_the_invocation_retries() -> None:
    client = boto3.client("bedrock-agent", region_name="us-east-1")
    with Stubber(client) as stub:
        stub.add_client_error("start_ingestion_job", service_error_code="ConflictException", http_status_code=409)
        with pytest.raises(ClientError, match="ConflictException"):
            ingest.start_ingestion(S3_EVENT, client, ENV)
