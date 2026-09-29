# 0004. Evaluation gates and their thresholds

## Status

Accepted

## Context

RAG quality degrades quietly: a chunking change, a corpus edit or a selection bug still returns fluent answers. The
client needs a check that fails a change before it ships, and it must run in CI without AWS credentials.

## Decision

- A 40-question golden set (`data/golden.jsonl`): 34 answerable questions with their relevant documents and expected
  facts, and 6 unanswerable questions.
- An offline harness runs retrieval over the fixture corpus with embedding fixtures and runs the production answering
  code with an extractive stand-in model.
- `make verify` fails when the chosen strategy scores below the thresholds in `data/eval.yaml`:

  | Metric | Threshold | Offline score when set |
  | --- | --- | --- |
  | Recall@5 | 0.90 | 0.971 |
  | MRR | 0.80 | 0.864 |
  | Citation precision | 0.70 | 0.750 |
  | Answered with a relevant citation | 0.80 | 0.853 |
  | Refused unanswerable questions | 0.80 | 1.000 |

- "Answer contains the expected facts" (0.80) is gated only in the live run, where a real model writes the answer.
- Thresholds sit a margin below the recorded scores: a single-question change does not fail CI, a lost document or a
  broken chunker does.

## Consequences

- Offline scores are proxies: the fixture embeddings are not Titan embeddings. They gate regressions in the pipeline;
  they do not certify production quality. The live run (`make test-live`) reports the same metrics against the
  deployed knowledge base.
- Raising a threshold or changing the golden set is a reviewed change to `data/eval.yaml` or `data/golden.jsonl`, and the
  report tables are regenerated from the code (`make report-data`).

## Compliance

- `make data-check` and `tests/test_evaluation.py::test_offline_evaluation_meets_the_thresholds`.
- `make report-check` fails when the report tables differ from what the evaluation produces.

## Notes

Metrics are at document level: several chunks of one document count once, at their best rank.
