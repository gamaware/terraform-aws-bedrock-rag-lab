#!/usr/bin/env bash
# Manual end-to-end test against a real AWS account (make test-live). Never runs in CI.
#
# Runs only in the maintainer's personal sandbox account: the profile is fixed to "personal", and the account it
# resolves to must equal LIVE_ACCOUNT_ID, which the maintainer exports for the run and never commits. Any other
# account stops the script before anything is created.
#
# Creates nothing public: every plan goes through scripts/check_live_plan.py before apply (no internet or NAT
# gateway, no public subnet or route, API endpoint PRIVATE, no open bucket, queue or topic policy, no Route 53) and
# every taggable resource must carry Lab, Ephemeral=true, purpose=portfolio-test and run (IAM tag keys ignore case,
# so "Lab" rather than a second "project"). Everything is destroyed on exit (success,
# failure or Ctrl-C), then the script lists anything still tagged with this run.
#
# Steps: data stack, knowledge-base stack, upload the fixture corpus, one ingestion job, api stack, then
#   1. the golden-set evaluation against the real knowledge base, model and guardrail (harbor_eval.evaluate --live),
#   2. the guardrail red-team set through ApplyGuardrail (harbor_eval.guardrail_live),
#   3. POST /ask through API Gateway's test-invoke (the private API has no public URL) and the function itself.
#
# Cost: under USD 1 for a run of about 40 minutes (three interface endpoints in two zones, embeddings for 33 short
# documents, about 80 Nova Lite calls with the guardrail, S3 Vectors requests). See docs/live-test.md.
#
# Env: LIVE_ACCOUNT_ID (required)  LIVE_REGION (default us-east-1)  LIVE_YES=1 skips the prompt
# Output: evaluation JSON in .eval-runs/ (git-ignored); Terraform state in a temporary directory.
set -euo pipefail

PROFILE="personal"
REGION="${LIVE_REGION:-us-east-1}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUN_ID="$(date +%s | tail -c 7)"
NAME="hgrag-$RUN_ID"
WORK="$(mktemp -d)"
RESULTS="$REPO_ROOT/.eval-runs/$RUN_ID"
LAB_TAG="terraform-aws-bedrock-rag-lab"

aws_cli() {
  aws --profile "$PROFILE" --region "$REGION" "$@"
}

if [ "${LIVE_ACCOUNT_ID:-}" = "" ]; then
  echo "Set LIVE_ACCOUNT_ID to the sandbox account ID for this run (not committed anywhere)." >&2
  exit 2
fi
echo "Account for this run (profile $PROFILE):"
aws sts get-caller-identity --profile "$PROFILE" --output table
ACCOUNT_ID="$(aws sts get-caller-identity --profile "$PROFILE" --query Account --output text)"
if [ "$ACCOUNT_ID" != "$LIVE_ACCOUNT_ID" ]; then
  echo "FAIL: profile $PROFILE resolves to a different account than LIVE_ACCOUNT_ID; nothing was created" >&2
  exit 1
fi
if [ "${LIVE_YES:-0}" != "1" ]; then
  read -r -p "Create and destroy $NAME in $REGION on this account? [y/N] " answer
  [ "$answer" = "y" ] || exit 1
fi

export AWS_PROFILE="$PROFILE"
export AWS_REGION="$REGION"
export TF_IN_AUTOMATION=1
mkdir -p "$RESULTS"

# Same relative layout as the repository: the stacks read config/guardrail.yaml and package src/harbor_rag.
mkdir -p "$WORK/repo/infra"
cp -R "$REPO_ROOT/infra/terraform" "$WORK/repo/infra/terraform"
cp -R "$REPO_ROOT/config" "$REPO_ROOT/src" "$WORK/repo/"
rm -rf "$WORK"/repo/infra/terraform/*/.terraform "$WORK"/repo/infra/terraform/*/build
DATA="$WORK/repo/infra/terraform/data"
KB="$WORK/repo/infra/terraform/knowledge-base"
API="$WORK/repo/infra/terraform/api"
TAGS="{\"Lab\"=\"$LAB_TAG\",\"Ephemeral\"=\"true\",\"purpose\"=\"portfolio-test\",\"run\"=\"$RUN_ID\"}"
COMMON=(-var "name=$NAME" -var "region=$REGION" -var "tags=$TAGS" -var log_retention_days=1)

teardown() {
  set +e
  echo "--- teardown"
  destroyed=1
  for dir in "$API" "$KB" "$DATA"; do
    if [ -f "$dir/terraform.tfstate" ]; then
      terraform -chdir="$dir" destroy -input=false -auto-approve -var-file="$dir/live.tfvars.json" "${COMMON[@]}" \
        || destroyed=0
    fi
  done
  if [ "$destroyed" = "0" ]; then
    echo "FAIL: teardown did not complete; state kept in $WORK/repo/infra/terraform, rerun its destroy" >&2
    exit 1
  fi
  echo "--- leftovers tagged run=$RUN_ID"
  arns="$(aws_cli resourcegroupstaggingapi get-resources \
    --tag-filters "Key=Lab,Values=$LAB_TAG" "Key=run,Values=$RUN_ID" \
    --query 'ResourceTagMappingList[].ResourceARN' --output text | tr '\t' '\n' | grep -v -e '^$' -e ':kms:' || true)"
  rm -rf "$WORK"
  if [ "$arns" != "" ]; then
    echo "Tagged resources still listed (the tagging API lags deletes; check each one by hand):" >&2
    echo "$arns" >&2
    exit 1
  fi
  echo "nothing left (KMS keys stay pending deletion for 30 days at no cost)"
}
trap teardown EXIT

# Plan, check the plan, apply exactly that plan.
deploy() {
  local dir="$1" label="$2"
  echo "--- $label"
  terraform -chdir="$dir" init -input=false > /dev/null
  terraform -chdir="$dir" plan -input=false -out="$WORK/$label.tfplan" -var-file="$dir/live.tfvars.json" \
    "${COMMON[@]}" > /dev/null
  terraform -chdir="$dir" show -json "$WORK/$label.tfplan" > "$WORK/$label-plan.json"
  if ! python3 "$REPO_ROOT/scripts/check_live_plan.py" "$WORK/$label-plan.json" \
    --require-tag "Lab=$LAB_TAG" --require-tag Ephemeral=true --require-tag purpose=portfolio-test \
    --require-tag "run=$RUN_ID"; then
    echo "FAIL: the $label plan is not private-only and tagged; nothing more was applied" >&2
    exit 1
  fi
  terraform -chdir="$dir" apply -input=false "$WORK/$label.tfplan" > /dev/null
}

out() {
  terraform -chdir="$1" output -raw "$2"
}

# The account-level invocation logging setting is left as it is; the live test does not own it.
echo '{"force_destroy": true, "enable_invocation_logging": false}' > "$DATA/live.tfvars.json"
deploy "$DATA" data

cat > "$KB/live.tfvars.json" <<JSON
{
  "force_destroy": true,
  "policies_bucket_arn": "$(out "$DATA" policies_bucket_arn)",
  "data_kms_key_arn": "$(out "$DATA" kms_key_arn)",
  "alarm_topic_arn": "$(out "$DATA" alerts_topic_arn)"
}
JSON
deploy "$KB" knowledge-base
KB_ID="$(out "$KB" knowledge_base_id)"
DS_ID="$(out "$KB" data_source_id)"

echo "--- upload the fixture corpus and ingest"
BUCKET="$(out "$DATA" policies_bucket_name)"
while read -r path key; do
  aws_cli s3 cp --only-show-errors "$path" "s3://$BUCKET/$key"
done < <(cd "$REPO_ROOT" && PYTHONPATH=src uv run --frozen python -m harbor_eval.corpus --upload-plan)
# The uploads also fire the EventBridge trigger; a job already running makes this call conflict, so retry.
for ((i = 0; i < 20; i++)); do
  if JOB_ID="$(aws_cli bedrock-agent start-ingestion-job --knowledge-base-id "$KB_ID" --data-source-id "$DS_ID" \
    --query ingestionJob.ingestionJobId --output text 2> /dev/null)"; then
    break
  fi
  sleep 15
done
for ((i = 0; i < 60; i++)); do
  status="$(aws_cli bedrock-agent get-ingestion-job --knowledge-base-id "$KB_ID" --data-source-id "$DS_ID" \
    --ingestion-job-id "$JOB_ID" --query ingestionJob.status --output text)"
  [ "$status" = "COMPLETE" ] && break
  [ "$status" = "FAILED" ] && { echo "FAIL: ingestion job failed" >&2; exit 1; }
  sleep 10
done
[ "$status" = "COMPLETE" ] || { echo "FAIL: ingestion did not finish in 10 minutes" >&2; exit 1; }
aws_cli bedrock-agent get-ingestion-job --knowledge-base-id "$KB_ID" --data-source-id "$DS_ID" \
  --ingestion-job-id "$JOB_ID" --query ingestionJob.statistics --output table

cat > "$API/live.tfvars.json" <<JSON
{
  "knowledge_base_id": "$KB_ID",
  "knowledge_base_arn": "$(out "$KB" knowledge_base_arn)",
  "guardrail_id": "$(out "$KB" guardrail_id)",
  "guardrail_arn": "$(out "$KB" guardrail_arn)",
  "guardrail_version": "$(out "$KB" guardrail_version)",
  "kb_kms_key_arn": "$(out "$KB" kms_key_arn)",
  "alarm_topic_arn": "$(out "$DATA" alerts_topic_arn)",
  "monthly_budget_usd": 10
}
JSON
deploy "$API" api

echo "--- golden-set evaluation against the deployed knowledge base, model and guardrail"
(cd "$REPO_ROOT" && PYTHONPATH=src uv run --frozen python -m harbor_eval.evaluate --live --check \
  --kb-id "$KB_ID" --model-id "$(out "$API" inference_profile_arn)" \
  --guardrail-id "$(out "$KB" guardrail_id)" --guardrail-version "$(out "$KB" guardrail_version)" \
  --profile "$PROFILE" --region "$REGION" --json "$RESULTS/evaluation.json")

echo "--- guardrail red-team set"
(cd "$REPO_ROOT" && PYTHONPATH=src uv run --frozen python -m harbor_eval.guardrail_live \
  --guardrail-id "$(out "$KB" guardrail_id)" --guardrail-version "$(out "$KB" guardrail_version)" \
  --profile "$PROFILE" --region "$REGION" | tee "$RESULTS/guardrail.txt")

echo "--- POST /ask through the private API (test-invoke, IAM-signed from the maintainer's session)"
API_ID="$(out "$API" api_id)"
RESOURCE_ID="$(aws_cli apigateway get-resources --rest-api-id "$API_ID" --query "items[?path=='/ask'].id" --output text)"
[ "$(aws_cli apigateway get-rest-api --rest-api-id "$API_ID" --query 'endpointConfiguration.types[0]' --output text)" \
  = "PRIVATE" ] || { echo "FAIL: API is not PRIVATE" >&2; exit 1; }
aws_cli apigateway test-invoke-method --rest-api-id "$API_ID" --resource-id "$RESOURCE_ID" --http-method POST \
  --body '{"question": "How many days does a customer have to return an item?"}' \
  --query '[status, body]' --output text | tee "$RESULTS/ask.txt"
grep -q '^200' "$RESULTS/ask.txt" || { echo "FAIL: POST /ask did not return 200" >&2; exit 1; }
grep -q '"citations": \[{' "$RESULTS/ask.txt" || { echo "FAIL: the answer has no citation" >&2; exit 1; }

echo "--- live test passed; results in .eval-runs/$RUN_ID"
