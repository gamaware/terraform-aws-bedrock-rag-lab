# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Ask function (`src/harbor_rag`): PII pre-filter, `Retrieve`, context selection with an absolute and a relative
  cut-off, `Converse` with the guardrail and grounding qualifiers, citation enforcement, retries with backoff, JSON
  logs with the redacted question, and embedded CloudWatch metrics. Ingestion trigger function.
- `BedrockPort` interface with a boto3 adapter, and a `FakeBedrock` plus hand-written response fixtures for the tests.
- Guardrail policy in `config/guardrail.yaml`: content filters, prompt-attack filter, three denied topics, PII masking
  and blocking, a loyalty-number regex, contextual grounding; the same file feeds the local pre-filter.
- Fixture corpus of 33 fictional policy documents with metadata sidecars, a 40-question golden set, and 18 guardrail
  red-team cases.
- Offline evaluation (`src/harbor_eval`): chunking strategies, a hybrid local retriever over embedding fixtures,
  recall@5, MRR, citation precision, answer-pipeline gates with thresholds, and a `--live` mode for the deployed stack.
- Cost model per question and per month from pinned prices, with a vector store comparison.
- Terraform stacks `data`, `knowledge-base` and `api` with mocked `terraform test` suites (20 runs).
- Live test for a sandbox account with a plan pre-flight that refuses public or untagged resources.
- Evaluation and cost report (`report/REPORT.md` and PDF) with tables generated from the code.
- Eight ADRs, runbook, live-test guide, CI (a `make verify` job next to the shared checks), OpenSSF Scorecard.

### Security

- Shared reusable workflows from `gamaware/.github` are called pinned to a full commit SHA.
