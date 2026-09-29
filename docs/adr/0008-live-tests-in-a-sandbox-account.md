# 0008. Live tests run only in a sandbox account, private-only and tagged

## Status

Accepted

## Context

The mocked tests prove configuration intent. They cannot prove IAM permissions, the knowledge base's ingestion, real
retrieval scores or guardrail verdicts. A live run creates real resources and spends real money, and a mistake in the
wrong account could affect other workloads.

## Decision

- `make test-live` uses the maintainer's `personal` profile only and stops unless the account it resolves to equals
  `LIVE_ACCOUNT_ID`, which the maintainer exports for the run and never commits.
- Every plan is written to JSON and checked by `scripts/check_live_plan.py` before apply: no internet or NAT gateway,
  no public subnet or default route, API endpoint `PRIVATE`, no bucket, queue, topic or API policy open to everyone,
  public access blocks fully on, no Route 53, and every taggable resource tagged `Lab`, `Ephemeral=true`,
  `purpose=portfolio-test` and the run ID.
  Unknown values count as violations, with one decidable exception: a policy built with `aws_iam_policy_document`
  whose only unknowns are values the configuration takes from managed resources (bucket, topic or endpoint IDs in a
  fresh plan). Its statements are checked from the plan, and a `${...}` policy variable in a condition does not count
  as a restriction. Resource policies in the stacks are written with that data source for this reason.
- The live run leaves the account-level invocation logging setting as it is.
- Teardown runs on any exit and then lists anything still tagged with the run.

## Consequences

- A run costs under USD 1 and about 40 minutes.
- The account-level API Gateway CloudWatch role setting keeps pointing at the deleted role after teardown; the next
  API that enables logging in that account and Region sets its own.

## Compliance

- `tests/test_live_plan_check.py` (part of `make verify`) covers the pre-flight checker, including fresh plans of the
  `data` and `api` stacks (`tests/fixtures/plans`) that must pass.
- `scripts/test-live.sh` exits before any apply when the account does not match or the checker reports a violation.

## Notes

The live test never uses corporate or shared accounts, and creates nothing reachable from the internet.
