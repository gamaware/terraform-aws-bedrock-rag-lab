# 0002. S3 Vectors over OpenSearch Serverless for the knowledge base

## Status

Accepted

## Context

Bedrock Knowledge Bases can store vectors in OpenSearch Serverless, Aurora PostgreSQL with pgvector, S3 Vectors and
third-party stores. The Harbor Goods corpus is about 200 documents (about 6,000 chunks), and the expected load is
thousands of questions a day during store hours. OpenSearch Serverless bills a minimum capacity whether or not it is
queried. The client asked for a cost per question it can defend.

## Decision

Store the embeddings in an S3 Vectors bucket and index, encrypted with a customer managed KMS key. The index uses
1,024 dimensions, cosine distance and `float32`, matching Titan Text Embeddings V2. The chunk text and Bedrock's own
metadata are non-filterable keys, so the filterable metadata (`doc_type`, `title`, `doc_id`) stays within the per-vector
limit.

## Consequences

- The vector store costs cents a month for this corpus, against a floor of about USD 175 (dev/test) to USD 350
  (production redundancy) for OpenSearch Serverless and about USD 44 for Aurora Serverless v2 at 0.5 ACU (report
  section 6).
- Query latency is in the hundreds of milliseconds, which is small next to the model call.
- The knowledge base cannot use hybrid (keyword plus vector) search on S3 Vectors; the offline evaluation shows what
  vector-only retrieval costs in recall (report section 2) and the live run measures it with real embeddings.
- Hierarchical chunking stores parent text in metadata and meets the metadata limit sooner (ADR 0006).

## Compliance

- `infra/terraform/knowledge-base/tests/knowledge_base.tftest.hcl`: storage type `S3_VECTORS`, the index this stack
  creates, dimension and metric matching the embedding model, non-filterable keys, KMS encryption.
- `tests/test_cost_model.py`: S3 Vectors has the lowest monthly floor at every modeled volume.

## Notes

Revisit if the corpus grows past a few million vectors, if hybrid search becomes necessary for part numbers and codes,
or if sustained query volume makes the per-query price exceed an OpenSearch Serverless floor.
