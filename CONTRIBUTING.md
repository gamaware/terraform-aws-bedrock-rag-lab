# Contributing

This repository is a portfolio lab. Issues and pull requests are welcome for bugs, broken links and unclear
documentation.

1. Work on a branch; `main` is protected and accepts squash merges only.
2. Install the hooks once: `pre-commit install`.
3. Run `make verify` before pushing. It needs no AWS credentials and must end with `verify: all checks passed`.
4. Use [Conventional Commits](https://www.conventionalcommits.org/) for commit messages and pull request titles.
5. A change to the golden set, the corpus, the guardrail policy or `data/prices.yaml` also updates
   `report/REPORT.md` (`make report-data`) and the PDF (`make report`).

Do not add real account IDs, ARNs, IP addresses or personal data. Use the AWS documentation example IDs and the
fictional Harbor Goods names.
