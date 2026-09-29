# Copilot code review instructions

When reviewing pull requests in this repository:

- Flag any suppressed lint rule or scanner skip that lacks a reason next to the code.
- The API must stay private: API Gateway endpoint type `PRIVATE`, `AWS_IAM` authorization, and a resource policy that
  only allows the VPC endpoint. No internet gateway, NAT gateway or public subnet in the `api` stack.
- IAM statements for the Lambda functions and the knowledge base role must name specific resources (one knowledge
  base, one inference profile and its model, one guardrail, one index). Flag new `*` resources.
- The guardrail policy lives in `config/guardrail.yaml`. Changes there need matching tests and a report update.
- Lambda code under `src/harbor_rag/` uses only the Python standard library and boto3 from the runtime.
- Unit tests must not call AWS: they use the `FakeBedrock` port or botocore's `Stubber`.
- Pull request workflows must not request `id-token: write` or read AWS secrets.
- Actions must be pinned by full commit SHA with the version in a comment.
- Only fictional names and AWS documentation example account IDs may appear; no real IDs, ARNs, IPs or emails.
- Verify conventional commit format in PR titles.
