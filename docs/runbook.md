# Runbook: Harbor Goods policy assistant

Operating guide for the platform team. Stack outputs are read with `terraform -chdir=infra/terraform/<stack> output`.

## Deploy or update

Apply the stacks in order, each with its own state: `data`, then `knowledge-base` (inputs from `data` outputs), then
`api` (inputs from both). The `terraform.tfvars.example` file in each stack lists the inputs.

1. `terraform -chdir=infra/terraform/<stack> plan -out=tfplan`, review, then `apply tfplan`.
2. After a change to `config/guardrail.yaml`, apply `knowledge-base` first (it publishes a new guardrail version and
   keeps the previous one), then pass the new `guardrail_version` output to `api`. The function never runs the
   draft. Delete versions no deployment pins any more with `aws bedrock delete-guardrail --guardrail-identifier ID
   --guardrail-version N`.
3. After a change under `src/harbor_rag/`, apply `api` and `knowledge-base`; both package the same directory.

## Re-ingest

Uploads to the policy bucket start an ingestion job through EventBridge. Each document needs its
`<name>.metadata.json` sidecar next to it (`make corpus-metadata` writes them for the fixture corpus).

- **Alarm `<name>-ingest-failed`:** a trigger failed after two retries, usually because a job was already running.
  Start one job by hand; it picks up every change since the last successful job:

  ```bash
  aws bedrock-agent start-ingestion-job --knowledge-base-id KB_ID --data-source-id DS_ID
  aws bedrock-agent get-ingestion-job --knowledge-base-id KB_ID --data-source-id DS_ID --ingestion-job-id JOB_ID
  ```

  Then purge the dead-letter queue.
- **Documents failed in a job:** `get-ingestion-job` lists `failureReasons`. Common causes are an unsupported file
  type, a sidecar that is not valid JSON, or metadata over the per-vector limit (ADR 0002).
- **A document was deleted:** deletions also trigger a job; the data source deletes its vectors (`DELETE` policy).

## Rotate the model

1. Pick a model from the allowlist in `infra/terraform/api/variables.tf` (`answer_model_id`).
2. Run the live evaluation against a sandbox deployment with that model (`make test-live` after changing the default,
   or `python -m harbor_eval.evaluate --live --model-id ...` against an existing sandbox stack).
3. Compare with the recorded live results in `report/REPORT.md`. Ship only if every live gate passes.
4. Apply `api`. The inference profile is replaced; its cost allocation tag stays the same.

A model outside the allowlist needs a price in `data/prices.yaml`, a live evaluation and an ADR update first.

## Calibrate context selection

`min_score`, `relative_floor` and `max_sources` (variable `retrieval` in the api stack) decide which chunks the model
sees. The offline values do not carry over to Titan embeddings.

1. Run `python -m harbor_eval.evaluate --live ... --json run.json` with a range of `--min-score` values.
2. Pick the highest `min_score` that keeps "answered with a relevant citation" at its threshold; that maximizes
   refusals of unanswerable questions without losing answerable ones.
3. Set it in the `retrieval` variable, apply `api`, and record the live results in the report.

## Investigate a bad answer

1. Find the request in the function's log group (`/aws/lambda/<name>-ask`) by time or request ID. The `ask` log line
   identifies the question by `question_sha256` (the first 16 hex characters of the SHA-256 of the stripped
   question), `question_chars` and the PII types the pre-filter found (`redacted`); it never holds the question text.
   It also has the reason (`answered`, `no_context`, `no_citation`, `model_declined`, `guardrail`), the cited
   document URIs and the guardrail findings.
2. Get the question from whoever reported it and confirm it matches the hash
   (`printf '%s' "<question>" | shasum -a 256 | cut -c1-16`). Remove any customer data, then reproduce the retrieval:
   `aws bedrock-agent-runtime retrieve --knowledge-base-id KB_ID --retrieval-query text="<question>"`. Check whether
   the right document is in the results and what its score is.
3. Read the full model exchange in the invocation-log bucket (`bedrock/AWSLogs/...`) if invocation logging is on.
4. Classify and fix:
   - right document missing from the results: add the question to the golden set, then fix the document or chunking;
   - right document below the cut-off: calibrate selection (above);
   - answer wrong despite the right source: add the case to the golden set with its expected facts, then adjust the
     prompt or the model;
   - guardrail false positive: add the question to `data/fixtures/guardrail_cases.jsonl` as a clean case and adjust
     the topic definition or examples.
5. Every fix adds a golden-set or red-team case, so the gate catches a regression.

## Throttling and errors

- `503` with `Retry-After`: Bedrock throttled after three attempts. Check the `InvocationThrottles` metric and the
  account's on-demand quotas for the model; the reserved concurrency (`reserved_concurrency`) caps parallel calls.
- `502`: a non-retryable Bedrock error. The log line `ask_upstream_error` has the error code (for example
  `AccessDeniedException` after a guardrail version changed without an `api` apply).
- Alarm `<name>-guardrail-spike`: many interventions in five minutes. Check the findings in the logs: a prompt-injection
  attempt, a document that trips the grounding check, or a new PII format.

## Hand over

Subscribe on-call to the alerts topic (`alerts_topic_arn`), activate the `project` cost allocation tag, and share the
dashboard named after the deployment.
