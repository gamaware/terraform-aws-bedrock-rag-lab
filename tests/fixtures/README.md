# Test fixtures

`bedrock/*.json` are hand-written responses in the shape of the Amazon Bedrock `Retrieve` and `Converse` APIs,
including the guardrail trace. Values are fictional. They let the unit tests exercise every branch of the ask function
without a model call. When a live run shows a response shape these files do not cover, add a fixture here with the
personal data and account details removed.

`plans/*-fresh.json` are `terraform show -json` output for the `data` and `api` stacks planned against an empty
account, trimmed to `resource_changes` and `configuration`. They were planned offline (fake credentials, the provider's
account lookup skipped, all network traffic sent to a closed local port), with the documentation account ID
`111122223333` and the live-test tags. Bucket, topic and endpoint IDs are unknown in them, as they are in the first plan
of `make test-live`. The Lambda package hash is replaced by `PLACEHOLDER`. Regenerate them when a stack's policies
change.
