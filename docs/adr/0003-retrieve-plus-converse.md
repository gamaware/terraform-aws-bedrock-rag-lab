# 0003. Retrieve plus Converse instead of RetrieveAndGenerate

## Status

Accepted

## Context

Bedrock offers `RetrieveAndGenerate`, which retrieves, prompts and answers in one call. The client's requirements are
that answers cite their sources, never state a policy the sources do not contain, keep customer PII out, and have a
cost per question. Each of those needs control over a step `RetrieveAndGenerate` hides.

## Decision

The ask function calls `Retrieve`, selects the context itself, builds the prompt and calls `Converse` with the
guardrail:

- **Selection:** keep chunks above an absolute relevance cut-off (`min_score`) and within a share of the best score
  (`relative_floor`), merge chunks of one document into one numbered source, cap the sources and the context tokens.
- **Refusal without a model call** when nothing clears the cut-off.
- **Citations enforced in code:** the answer must cite at least one source number that was given; otherwise it is
  replaced by the refusal.
- **Guardrail with grounding:** the context goes in a `guardContent` block qualified `grounding_source` and the question
  in one qualified `query`, so the contextual grounding check compares the answer with exactly what the model saw.
- **Retries** for throttling and transient errors live in the function (full-jitter backoff); botocore retries are off
  so attempts are not multiplied.
- All Bedrock calls go through a `BedrockPort` interface, so every branch is unit-tested with a fake.

## Consequences

- More code than one API call: a few hundred lines, all covered by unit tests with no model call.
- Selection settings are Terraform variables and must be calibrated per embedding model (runbook).
- Token usage and guardrail verdicts are available per request for the metrics and the cost model.

## Compliance

- `tests/test_service.py`: refusal without context and without a model call, refusal without a valid citation,
  guardrail intervention, PII redaction before `Retrieve`, retries and error mapping.
- `tests/test_prompt.py`: selection, merging, token budget, the `guardContent` qualifiers and the guardrail config.

## Notes

The design follows the pattern of the MIT-0 samples credited in the README, rewritten for this function.
