# One entry point for local and CI runs: the CI verify job calls `make verify`. Offline: no AWS credentials and no
# AWS API calls. The first run downloads Python packages, Terraform providers and the tflint AWS ruleset.

SHELL := /usr/bin/env bash
.SHELLFLAGS := -euo pipefail -c
.DEFAULT_GOAL := help

UV ?= uv
RUN := $(UV) run --frozen
PY := PYTHONPATH=src $(RUN) python
CHECKOV ?= uvx --python 3.13 --from checkov==3.3.19 checkov
TF_STACKS := infra/terraform/data infra/terraform/knowledge-base infra/terraform/api
TFLINT_CONFIG := $(CURDIR)/.tflint.hcl
SHELL_SCRIPTS := $(wildcard scripts/*.sh)

export TF_IN_AUTOMATION := 1
export TF_INPUT := 0

.PHONY: help verify lint types test data-check eval cost report-data report-check report tf-fmt tf-verify \
	checkov trivy semgrep shell corpus-metadata embeddings test-live clean

help: ## List targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "} {printf "  %-16s %s\n", $$1, $$2}'

verify: lint types test data-check report-check tf-verify checkov trivy semgrep shell ## Run every offline check
	@echo "verify: all checks passed"

lint: ## ruff lint and format check
	$(RUN) ruff check src tests scripts
	$(RUN) ruff format --check src tests scripts

types: ## mypy (strict) on the Lambda and evaluation packages
	$(RUN) mypy

test: ## Unit tests, guardrail policy tests, offline evaluation gates, cost model, live pre-flight
	$(RUN) pytest

data-check: ## Corpus metadata, embedding fixtures and evaluation gates are current
	$(PY) -m harbor_eval.corpus --check
	$(PY) -m harbor_eval.embeddings --check
	$(PY) -m harbor_eval.evaluate --check > /dev/null
	@echo "pass  evaluation gates (make eval prints the table)"

eval: ## Offline retrieval and answer evaluation with the full table
	$(PY) -m harbor_eval.evaluate --check

cost: ## Cost per question and per month
	$(PY) -m harbor_eval.cost_model

report-data: ## Rewrite the generated tables in report/REPORT.md
	$(PY) -m harbor_eval.report_data

report-check: ## report/REPORT.md tables match the code, and report/REPORT.pdf was built from it
	$(PY) -m harbor_eval.report_data --check
	@shasum -a 256 --check --status report/REPORT.sha256 \
		|| { echo "FAIL  report/REPORT.pdf is out of date: run make report and commit it"; exit 1; }
	@echo "pass  report/REPORT.pdf matches report/REPORT.md"

report: ## Rebuild report/REPORT.pdf with the pinned pandoc/latex image (needs Docker)
	$(RUN) python scripts/build_report.py

tf-fmt: ## Rewrite Terraform files to canonical format
	terraform fmt -recursive infra/terraform

tf-verify: ## fmt check, validate, tflint and mocked terraform test for each stack
	terraform fmt -check -recursive infra/terraform
	for stack in $(TF_STACKS); do \
	  echo "--- $$stack"; \
	  terraform -chdir=$$stack init -backend=false -input=false > /dev/null; \
	  terraform -chdir=$$stack validate; \
	  (cd $$stack && tflint --init --config=$(TFLINT_CONFIG) > /dev/null && tflint --config=$(TFLINT_CONFIG)); \
	  terraform -chdir=$$stack test; \
	done

checkov: ## Policy checks on Terraform and workflows (.checkov.yaml); skips carry reasons in the code
	$(CHECKOV) --config-file .checkov.yaml

trivy: ## Trivy misconfiguration scan
	trivy config --quiet --exit-code 1 --severity HIGH,CRITICAL --skip-dirs '**/.terraform' --skip-dirs .venv .

semgrep: ## Semgrep static analysis (the rules are fetched from the registry)
	semgrep scan --quiet --error --metrics=off --config p/default --config p/python --config p/terraform \
		--exclude .venv --exclude '.terraform' src scripts infra

shell: ## shellcheck and shellharden on every script
	shellcheck --severity=style $(SHELL_SCRIPTS)
	shellharden --check $(SHELL_SCRIPTS)

corpus-metadata: ## Regenerate the .metadata.json sidecars of data/corpus
	$(PY) -m harbor_eval.corpus

embeddings: ## Regenerate data/fixtures/embeddings.json
	$(PY) -m harbor_eval.embeddings

test-live: ## Manual: deploy to the maintainer's sandbox account, evaluate live, destroy (docs/live-test.md)
	scripts/test-live.sh

clean: ## Remove caches and local Terraform working directories
	rm -rf .pytest_cache .ruff_cache .mypy_cache infra/terraform/*/.terraform infra/terraform/*/build
