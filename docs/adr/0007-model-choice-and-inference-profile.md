# 0007. Nova Lite by default, through an application inference profile

## Status

Accepted

## Context

The answering model writes two or three sentences from at most three short sources. The cost model shows the model is
a small part of the cost per question with Nova Lite and about half of it with Claude Haiku. The client wants spend on
the assistant visible in Cost Explorer, separate from other Bedrock use in the account.

## Decision

- Default model: Amazon Nova Lite (`amazon.nova-lite-v1:0`). Evaluated alternatives in the allowlist: Nova Micro and
  Claude Haiku 4.5 through the US cross-Region inference profile. Terraform refuses any other model ID.
- The function calls an application inference profile copied from the chosen model, tagged for cost allocation.
- IAM allows `InvokeModel` only on that profile and its underlying model (in every Region of a cross-Region profile).

## Consequences

- Switching to Claude Haiku is a one-variable change, about double the cost per question, and needs its own live
  evaluation before production.
- The profile's tags need the cost allocation tag activated once in the billing console.

## Compliance

- `infra/terraform/api/tests/api.tftest.hcl`: model allowlist, profile wrapping Nova Lite by default, cross-Region
  profile ARNs, IAM limited to the profile and its model.
- `tests/test_cost_model.py`: every allowed model has a pinned price.

## Notes

If the live answer-quality gate fails with Nova Lite, the fallback order is: tune selection and prompt, then Claude
Haiku.
