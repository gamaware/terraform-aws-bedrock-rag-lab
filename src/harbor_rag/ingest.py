"""Lambda entry point for the EventBridge rule on the policy bucket: start a knowledge base ingestion job.

The client token is derived from the EventBridge event ID, so a redelivered event does not start a second job. A
`ConflictException` (a job for this data source is already running) is raised on purpose: the asynchronous
invocation retries later, and after the last retry the event lands in the dead-letter queue, which has an alarm.
"""

from __future__ import annotations

import json
import os
from functools import cache
from typing import TYPE_CHECKING, Any

import boto3

if TYPE_CHECKING:
    from mypy_boto3_bedrock_agent import AgentsforBedrockClient


@cache
def _client() -> AgentsforBedrockClient:
    return boto3.client("bedrock-agent")


def start_ingestion(event: dict[str, Any], client: AgentsforBedrockClient, env: dict[str, str]) -> dict[str, str]:
    key = str(event.get("detail", {}).get("object", {}).get("key", ""))
    response = client.start_ingestion_job(
        knowledgeBaseId=env["KNOWLEDGE_BASE_ID"],
        dataSourceId=env["DATA_SOURCE_ID"],
        clientToken=f"s3-event-{event['id']}",
        description=f"S3 change: {key}"[:200],
    )
    job = response["ingestionJob"]
    result = {"event": "ingestion_started", "job_id": job["ingestionJobId"], "status": job["status"], "key": key}
    print(json.dumps(result))
    return result


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, str]:
    return start_ingestion(event, _client(), dict(os.environ))
