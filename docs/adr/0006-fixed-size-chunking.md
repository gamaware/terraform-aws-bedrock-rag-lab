# 0006. Fixed-size chunking at 100 tokens

## Status

Accepted

## Context

Knowledge Bases can chunk documents with a fixed size, hierarchically, semantically or not at all. The choice changes
what the retriever can rank and what the model reads. Semantic chunking calls a model during ingestion, so it cannot be
compared offline. Harbor Goods' policy documents are short and sectioned.

## Decision

Fixed-size chunks of 100 tokens with 20 percent overlap, chosen from the offline comparison in report section 2:
fixed-100 keeps the best recall@5 and raises MRR over 300-token chunks (identical to one chunk per document at this
document length). Hierarchical chunking had a slightly higher MRR but lower recall, and on S3 Vectors its parent text
counts against the per-vector metadata limit.

## Consequences

- More, smaller vectors (50 against 33 for the fixture corpus); storage cost stays negligible (ADR 0002).
- A Bedrock token is shorter than the word the offline chunker counts, so production chunks hold about 75 words. The
  live evaluation re-checks the decision with Titan embeddings; `chunk_max_tokens` is a variable, and changing it
  re-chunks on the next ingestion.

## Compliance

- `infra/terraform/knowledge-base/tests/knowledge_base.tftest.hcl`: `FIXED_SIZE`, 100 tokens, 20 percent overlap.
- `data/eval.yaml` names the chosen strategy, and `make data-check` gates its scores.

## Notes

Revisit when the corpus includes long PDFs, where hierarchical chunking usually helps more than on short policies.
