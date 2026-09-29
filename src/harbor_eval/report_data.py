"""Write the generated tables into report/REPORT.md between `<!-- generated:NAME -->` and `<!-- /generated:NAME -->`.

    python -m harbor_eval.report_data            # rewrite the blocks
    python -m harbor_eval.report_data --check    # fail if a block differs from what the data produces

Every number in those blocks comes from the offline evaluation and the cost model, so the report cannot drift from
the code that produced it.
"""

from __future__ import annotations

import argparse
import re
import sys
import textwrap
from collections.abc import Mapping
from typing import Any

from harbor_eval import ROOT
from harbor_eval.chunking import STRATEGIES
from harbor_eval.cost_model import build
from harbor_eval.evaluate import load_config, run_offline

REPORT = ROOT / "report" / "REPORT.md"


def _wrap(text: str) -> str:
    return "\n".join(textwrap.wrap(text, width=118, break_on_hyphens=False))


def _usd(value: float) -> str:
    return f"{value:,.2f}"


def retrieval_table(results: Mapping[str, Any]) -> str:
    unanswerable = sum("refused" in row for row in results["answers"]["questions"])
    rows = [
        "| Chunking | Chunks | Recall@5 | MRR | Citation precision | Unanswerable with context |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name, per_mode in results["retrieval"].items():
        m = per_mode["hybrid"]
        label = f"**{name}** (chosen)" if name == results["strategy"] else name
        rows.append(
            f"| {label}: {STRATEGIES[name].note} | {per_mode['chunks']} | {m['recall_at_5']:.3f} | {m['mrr']:.3f} "
            f"| {m['citation_precision']:.3f} | {m['unanswerable_with_context']} of {unanswerable} |"
        )
    return "\n".join(rows)


def mode_table(results: Mapping[str, Any]) -> str:
    per_mode = results["retrieval"][results["strategy"]]
    rows = ["| Retriever (chosen chunking) | Recall@5 | MRR | Citation precision |", "| --- | ---: | ---: | ---: |"]
    for mode in ("hybrid", "lexical", "vector"):
        m = per_mode[mode]
        rows.append(f"| {mode} | {m['recall_at_5']:.3f} | {m['mrr']:.3f} | {m['citation_precision']:.3f} |")
    return "\n".join(rows)


def gate_table(results: Mapping[str, Any], config: Mapping[str, Any]) -> str:
    chosen = results["retrieval"][results["strategy"]]["hybrid"]
    answers = results["answers"]
    values = {**chosen, **answers}
    labels = {
        "recall_at_5": "Recall@5",
        "mrr": "MRR",
        "citation_precision": "Citation precision",
        "answered_with_relevant_citation": "Answered with a relevant citation",
        "refusal_on_unanswerable": "Refused unanswerable questions",
    }
    rows = ["| Gate | Offline score | Threshold | Result |", "| --- | ---: | ---: | --- |"]
    for key, limit in config["thresholds"].items():
        rows.append(f"| {labels[key]} | {values[key]:.3f} | {limit} | {'pass' if values[key] >= limit else 'FAIL'} |")
    live = config["live_thresholds"]["answer_contains_expected"]
    rows.append(
        f"| Answer contains the expected facts | {answers['answer_contains_expected']:.3f} (stand-in model) "
        f"| {live} (live only) | not gated offline |"
    )
    return "\n".join(rows)


def cost_table(cost: Mapping[str, Any]) -> str:
    rows = [
        "| Model | Model | Guardrail | Embedding, retrieval | Lambda, API, logs | Per 1,000 questions |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for model, c in cost["per_model"].items():
        rows.append(
            f"| `{model}` | {_usd(c.model * 1000)} | {_usd(c.guardrail * 1000)} "
            f"| {_usd((c.embedding + c.retrieval) * 1000)} | {_usd(c.compute * 1000)} | **{_usd(c.total * 1000)}** |"
        )
    return "\n".join(rows)


def monthly_table(cost: Mapping[str, Any]) -> str:
    rows = [
        "| Questions per month | Per-question costs | Fixed costs | Total per month |",
        "| ---: | ---: | ---: | ---: |",
    ]
    for q, m in cost["monthly"].items():
        rows.append(f"| {q:,} | {_usd(m['variable'])} | {_usd(m['fixed'])} | **{_usd(m['total'])}** |")
    rows.append("")
    rows.append(_wrap("Fixed costs: " + "; ".join(f"{k} USD {_usd(v)}" for k, v in cost["fixed"].items()) + "."))
    return "\n".join(rows)


def store_table(cost: Mapping[str, Any]) -> str:
    volumes = list(cost["vector_stores"])
    header = "| Vector store | " + " | ".join(f"{q:,} questions" for q in volumes) + " |"
    rows = [header, "| --- |" + " ---: |" * len(volumes)]
    for store in cost["vector_stores"][volumes[0]]:
        cells = " | ".join(_usd(cost["vector_stores"][q][store]) for q in volumes)
        rows.append(f"| {store} | {cells} |")
    return "\n".join(rows)


def blocks() -> dict[str, str]:
    config = load_config()
    results = run_offline(config)
    answers = results["answers"]
    cost = build(answers["mean_input_tokens"])
    return {
        "retrieval": retrieval_table(results),
        "modes": mode_table(results),
        "gates": gate_table(results, config),
        "tokens": _wrap(
            f"Mean prompt size over the {answers['model_calls']} questions that reached the model: "
            f"**{answers['mean_input_tokens']} input tokens**. Answer length assumed: "
            f"**{cost['output_tokens']} output tokens**."
        ),
        "cost": cost_table(cost),
        "monthly": monthly_table(cost),
        "stores": store_table(cost),
    }


def render(report: str, generated: Mapping[str, str]) -> str:
    for name, body in generated.items():
        pattern = re.compile(rf"(<!-- generated:{name} -->\n).*?(<!-- /generated:{name} -->)", re.DOTALL)
        match = pattern.search(report)
        if match is None:
            raise KeyError(f"report/REPORT.md has no generated:{name} block")
        report = report[: match.start()] + match.group(1) + body + "\n" + match.group(2) + report[match.end() :]
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    current = REPORT.read_text(encoding="utf-8")
    expected = render(current, blocks())
    if args.check:
        if current != expected:
            print("FAIL  report/REPORT.md tables are stale (run make report-data, then make report)")
            return 1
        print("pass  report/REPORT.md tables match the evaluation and the cost model")
        return 0
    REPORT.write_text(expected, encoding="utf-8")
    print("wrote report/REPORT.md tables")
    return 0


if __name__ == "__main__":
    sys.exit(main())
