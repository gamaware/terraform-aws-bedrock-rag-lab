# 0001. Private API with IAM authorization, reached through VPC endpoints

## Status

Accepted

## Context

The assistant is for Harbor Goods staff, not customers. Its answers quote internal policies, and questions may carry
customer details. Staff tools already run inside the corporate network, which connects to the AWS VPCs. An
internet-facing endpoint would need a WAF, an identity provider integration and abuse monitoring that an internal
tool does not otherwise need.

## Decision

- API Gateway REST API with endpoint type `PRIVATE`, reachable only through an `execute-api` interface endpoint in
  the assistant's VPC.
- A resource policy that denies every call not arriving through that endpoint (`aws:SourceVpce`), and allows only
  principals of the Harbor Goods account.
- `AWS_IAM` authorization on `POST /ask`: callers sign requests with SigV4 and need `execute-api:Invoke`.
- The ask function runs in two private subnets with no internet gateway, no NAT gateway and no default route. It
  reaches Bedrock through `bedrock-runtime` and `bedrock-agent-runtime` interface endpoints whose policies allow only
  this account's principals and only the knowledge base, inference profile, model and guardrail of this deployment.

## Consequences

- Nothing in the design is reachable from the internet, and a failed teardown leaves nothing public behind.
- Three interface endpoints in two zones are the largest fixed cost, about USD 44 a month (report section 5).
- Clients must sign requests. The staff portal's backend does this with its own role; a browser cannot call the API
  directly.
- A regional or edge API with a Cognito authorizer would be the change if the assistant were ever offered outside the
  corporate network.

## Compliance

- `infra/terraform/api/tests/api.tftest.hcl`: endpoint type `PRIVATE`, `AWS_IAM` authorization, the `aws:SourceVpce`
  deny, an empty route table, no public IPs, interface endpoints only, and HTTPS egress to the endpoint security group
  only.
- `scripts/check_live_plan.py` refuses any plan with an internet or NAT gateway, a non-private API, a default route or
  open ingress before the live test applies it.

## Notes

The execute-api endpoint uses private DNS, so clients inside the VPC (and networks routed into it) call the standard
`https://{api-id}.execute-api.{region}.amazonaws.com/v1/ask` URL.
