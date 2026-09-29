# Architecture decision records

Architecture decision records follow the *Fundamentals of Software Architecture* (2nd ed.) format.
Records are never deleted; a replaced decision is marked Superseded and links to its successor.

| Number | Title | Status |
| --- | --- | --- |
| [0001](0001-private-api-with-iam-auth.md) | Private API with IAM authorization, reached through VPC endpoints | Accepted |
| [0002](0002-s3-vectors-over-opensearch-serverless.md) | S3 Vectors over OpenSearch Serverless for the knowledge base | Accepted |
| [0003](0003-retrieve-plus-converse.md) | Retrieve plus Converse instead of RetrieveAndGenerate | Accepted |
| [0004](0004-evaluation-gates.md) | Evaluation gates and their thresholds | Accepted |
| [0005](0005-guardrail-and-pii-prefilter.md) | Guardrail policy as data, with a local PII pre-filter | Accepted |
| [0006](0006-fixed-size-chunking.md) | Fixed-size chunking at 100 tokens | Accepted |
| [0007](0007-model-choice-and-inference-profile.md) | Nova Lite by default, through an application inference profile | Accepted |
| [0008](0008-live-tests-in-a-sandbox-account.md) | Live tests run only in a sandbox account, private-only and tagged | Accepted |
