# Live test

`make test-live` proves what the mocked tests cannot: IAM permissions, the knowledge base's ingestion, real retrieval
scores, guardrail verdicts and the private API path. It is manual and never runs in CI.

## Where it runs

Only in the maintainer's personal sandbox account (ADR 0008):

```bash
export LIVE_ACCOUNT_ID=YOUR_SANDBOX_ACCOUNT_ID   # the script stops if the profile resolves elsewhere
make test-live
```

The script uses the `personal` AWS CLI profile, prints the caller identity and asks for confirmation (`LIVE_YES=1`
skips the prompt). Region defaults to `us-east-1` (`LIVE_REGION`).

Before the first run: set an AWS Budget with an alert in the sandbox account, and confirm access to Amazon Nova Lite and
Titan Text Embeddings V2 in the Bedrock console.

## What it does

1. Copies `infra/terraform`, `config` and `src` to a temporary directory, so no state lands in the repository.
2. For each stack (`data`, `knowledge-base`, `api`): plan, write the plan as JSON, run `scripts/check_live_plan.py`
   (nothing public; every taggable resource tagged `Lab`, `Ephemeral=true`, `purpose=portfolio-test` and the run
   ID), then apply that exact plan.
3. Uploads the fixture corpus with its metadata sidecars and waits for one ingestion job to complete.
4. Runs the golden-set evaluation against the deployed knowledge base, model and guardrail
   (`harbor_eval.evaluate --live --check`) and fails below the offline thresholds or the live-only answer threshold;
   results go to `.eval-runs/<run>/evaluation.json`.
5. Sends the 18 red-team cases through `ApplyGuardrail`, in the same blocks and qualifiers as the production
   `Converse` request, and fails on any unexpected verdict.
6. Calls `POST /ask` through API Gateway's test-invoke (the API has no public URL) and checks for a `200` with at least
   one citation.
7. Destroys the three stacks in reverse order on any exit, then lists anything still tagged with the run.

## Cost

Under USD 1 for a run of about 40 minutes: three interface endpoints in two zones for under an hour (about USD 0.06),
embeddings for 33 short documents, about 80 Nova Lite calls with the guardrail, and S3 Vectors requests. KMS keys stay
pending deletion for 30 days at no cost.

## After a run

Copy the live gate results into `report/REPORT.md` (a new "Live results" section), set the calibrated `min_score` in
the api stack defaults if it changed, run `make report-data` and `make report`, and commit.

## Known effects on the account

- Model invocation logging is not touched (`enable_invocation_logging = false` in the run).
- The account-level API Gateway CloudWatch role setting keeps pointing at the deleted role; the next API with logging
  sets its own.
