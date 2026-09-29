# Test fixtures

`bedrock/*.json` are hand-written responses in the shape of the Amazon Bedrock `Retrieve` and `Converse` APIs,
including the guardrail trace. Values are fictional. They let the unit tests exercise every branch of the ask function
without a model call. When a live run shows a response shape these files do not cover, add a fixture here with the
personal data and account details removed.
