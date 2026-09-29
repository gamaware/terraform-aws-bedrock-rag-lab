# 0005. Guardrail policy as data, with a local PII pre-filter

## Status

Accepted

## Context

Staff paste customer details into questions. The client requires that customer PII stays out of answers and logs,
that the assistant declines legal advice and competitor pricing, and that it resists prompt injection. A Bedrock
guardrail covers these, but only for text that passes through `Converse` or `ApplyGuardrail`. The question also goes to
`Retrieve`, where it is embedded, and into the function's logs.

## Decision

- The guardrail policy is one YAML file, `config/guardrail.yaml`: content filters, denied topics with examples, PII
  entities (mask or block), a custom regex for the loyalty number, and contextual grounding thresholds (grounding
  0.75, relevance 0.5).
- Terraform builds the guardrail from that file and publishes a version whenever it changes; the api stack refuses
  `DRAFT` and pins the published version.
- The same file has a `prefilter` list of regular expressions. Terraform passes it to the ask function, which redacts
  the question before `Retrieve`, with the guardrail's `{TYPE}` placeholder style. It also redacts citation excerpts,
  which are source text the guardrail does not assess.
- Logs never carry the question text, redacted or not: the `ask` line has a SHA-256 prefix, the length and the PII
  types found.
- Entities that a regular expression cannot catch (names, addresses) are listed in `prefilter_exempt` with the reason;
  the guardrail screens the question (qualified `guard_content`) and masks them in the answer.
- Card, Social Security and bank account numbers are blocked rather than masked.

## Consequences

- One reviewed file changes the policy for Terraform, the function and the tests together.
- Publishing a version keeps the previous one, so the function keeps working until the api stack moves its pin; old
  versions are deleted by hand once nothing pins them (runbook).
- The pre-filter can miss formats; the guardrail remains the control of record, and the red-team set grows with the
  intervention findings from production.
- A grounding threshold of 0.75 withholds some correct but loosely phrased answers; the live run and the first weeks of
  intervention metrics decide whether to move it.

## Compliance

- `tests/test_guardrail_policy.py`: Bedrock limits for topics, examples per topic, prompt-attack on input, blocked
  identifiers, every PII entity covered by a pattern or a reason, the regex copy matching the guardrail.
- `tests/test_pii.py`: every red-team case gets exactly the expected pre-filter result, with no false positives on the
  clean look-alikes.
- `infra/terraform/knowledge-base/tests/knowledge_base.tftest.hcl` and `infra/terraform/api/tests/api.tftest.hcl`: the
  guardrail is built from the file; the function receives the pre-filter from the file and the pinned version.
- `tests/test_handler.py`: a question with a name and a street address leaves no trace in the logs, answered or
  refused for lack of context.
- `make test-live`: the 18 red-team cases through `ApplyGuardrail`, in the block shape and qualifiers of the
  production `Converse` request.

## Notes

Guardrail policy design follows the ideas of the Amazon Bedrock Guardrails workshop, cited in the README; no workshop
text or code is copied.
