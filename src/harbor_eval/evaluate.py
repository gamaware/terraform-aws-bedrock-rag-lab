"""Retrieval and answer evaluation over the golden set.

    python -m harbor_eval.evaluate              # offline: every chunking strategy, then answers; prints a summary
    python -m harbor_eval.evaluate --check      # also fail when the chosen strategy is below data/eval.yaml
    python -m harbor_eval.evaluate --json out   # write the full results (per question) as JSON
    python -m harbor_eval.evaluate --live ...   # the same metrics against the deployed stack; with --check it also
                                                # gates live_thresholds (answer contains the expected facts)

Metrics (answerable questions, document level): recall@5, MRR, citation precision (share of the sources the ask
function selects for the model that are relevant). Answers: share of answerable questions answered with a citation of
a relevant document, share whose answer also contains every expected phrase, and share of unanswerable questions
refused. Offline, the answers come from an extractive stand-in (harbor_eval.offline), so "contains expected" is
reported but only gated in the live run; the pipeline metrics are gated in both.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from statistics import mean
from typing import Any

import yaml

from harbor_eval import DATA
from harbor_eval.chunking import STRATEGIES, chunk_corpus
from harbor_eval.corpus import load
from harbor_eval.embeddings import load_fixture
from harbor_eval.golden import GoldenQuestion, load_golden
from harbor_eval.metrics import citation_precision, ranked_docs, recall_at_k, reciprocal_rank
from harbor_eval.offline import LocalBedrock
from harbor_eval.retriever import LocalRetriever
from harbor_rag.config import Settings
from harbor_rag.port import BedrockPort
from harbor_rag.prompt import select_sources
from harbor_rag.service import answer_question

MODES = ("hybrid", "lexical", "vector")


def load_config(path: Path = DATA / "eval.yaml") -> dict[str, Any]:
    config: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    return config


def _doc_id(result: Mapping[str, Any]) -> str:
    return str(result.get("metadata", {}).get("doc_id", ""))


def score_retrieval(
    results_by_question: Mapping[str, Sequence[Mapping[str, Any]]],
    golden: Sequence[GoldenQuestion],
    selection: Mapping[str, Any],
) -> dict[str, Any]:
    rows = []
    for q in golden:
        results = results_by_question[q.qid]
        ranked = ranked_docs([_doc_id(r) for r in results])
        selected = select_sources(
            results,
            max_sources=selection["max_sources"],
            min_score=selection["min_score"],
            relative_floor=selection["relative_floor"],
        )
        cited = [s.uri.rsplit("/", 1)[-1].removesuffix(".md") for s in selected]
        row: dict[str, Any] = {"id": q.qid, "top": ranked[:5], "selected": cited}
        if q.answerable:
            row |= {
                "recall_at_5": recall_at_k(ranked, q.relevant, 5),
                "rr": reciprocal_rank(ranked, q.relevant),
                "citation_precision": citation_precision(cited, q.relevant),
            }
        else:
            row["context_selected"] = bool(selected)
        rows.append(row)
    answerable = [r for r in rows if "recall_at_5" in r]
    unanswerable = [r for r in rows if "context_selected" in r]
    return {
        "recall_at_5": round(mean(r["recall_at_5"] for r in answerable), 3),
        "mrr": round(mean(r["rr"] for r in answerable), 3),
        "citation_precision": round(mean(r["citation_precision"] for r in answerable), 3),
        "unanswerable_with_context": sum(r["context_selected"] for r in unanswerable),
        "questions": rows,
    }


def score_answers(
    port: BedrockPort, settings: Settings, golden: Sequence[GoldenQuestion], *, timed: bool = False
) -> dict[str, Any]:
    """Answer every golden question. `timed` (live runs) records wall-clock latency per question, retrieval included."""
    rows = []
    latencies: list[float] = []
    for q in golden:
        started = time.perf_counter()
        answer = answer_question(q.question, port=port, settings=settings, sleep=lambda _: None)
        latencies.append((time.perf_counter() - started) * 1000)
        cited = [c["uri"].rsplit("/", 1)[-1].removesuffix(".md") for c in answer.citations]
        text = answer.answer.lower()
        row: dict[str, Any] = {"id": q.qid, "reason": answer.reason, "cited": cited, "usage": answer.usage}
        if timed:
            row["latency_ms"] = round(latencies[-1])
        if q.answerable:
            row["relevant_citation"] = not answer.refused and any(d in q.relevant for d in cited)
            row["correct"] = row["relevant_citation"] and all(p.lower() in text for p in q.must_include)
        else:
            row["refused"] = answer.refused
        rows.append(row)
    answerable = [r for r in rows if "correct" in r]
    unanswerable = [r for r in rows if "refused" in r]
    usages = [r["usage"] for r in rows if r["usage"]]
    timing = {}
    if timed:
        ordered = sorted(latencies)
        timing = {
            "latency_p50_ms": round(ordered[len(ordered) // 2]),
            "latency_p95_ms": round(ordered[min(len(ordered) - 1, math.ceil(0.95 * len(ordered)) - 1)]),
            "latency_max_ms": round(ordered[-1]),
        }
    return {
        "answered_with_relevant_citation": round(mean(r["relevant_citation"] for r in answerable), 3),
        "answer_contains_expected": round(mean(r["correct"] for r in answerable), 3),
        "refusal_on_unanswerable": round(mean(r["refused"] for r in unanswerable), 3),
        "model_calls": len(usages),
        "mean_input_tokens": round(mean(u["inputTokens"] for u in usages)) if usages else 0,
        "mean_output_tokens": round(mean(u["outputTokens"] for u in usages)) if usages else 0,
        **timing,
        "questions": rows,
    }


def run_offline(config: Mapping[str, Any]) -> dict[str, Any]:
    docs = load()
    golden = load_golden()
    fixture = load_fixture()
    k = config["number_of_results"]
    retrieval: dict[str, dict[str, Any]] = {}
    for name, strategy in STRATEGIES.items():
        chunks = chunk_corpus(docs, strategy)
        retrieval[name] = {"chunks": len(chunks)}
        for mode in MODES:
            retriever = LocalRetriever(chunks, fixture["chunks"][name], mode)
            results = {
                q.qid: retriever.retrieve(q.question, fixture["queries"][q.qid], k)["retrievalResults"] for q in golden
            }
            retrieval[name][mode] = score_retrieval(results, golden, config["offline_selection"])

    chosen = config["strategy"]
    retriever = LocalRetriever(chunk_corpus(docs, STRATEGIES[chosen]), fixture["chunks"][chosen], "hybrid")
    query_vectors = {q.question: fixture["queries"][q.qid] for q in golden}
    selection = config["offline_selection"]
    settings = Settings(
        knowledge_base_id="offline",
        model_id="offline-extractive",
        guardrail_id="offline",
        guardrail_version="1",
        number_of_results=k,
        max_sources=selection["max_sources"],
        min_score=selection["min_score"],
        relative_floor=selection["relative_floor"],
    )
    answers = score_answers(LocalBedrock(retriever, query_vectors), settings, golden)
    return {"embedding_model": fixture["model"], "strategy": chosen, "retrieval": retrieval, "answers": answers}


def check(results: Mapping[str, Any], thresholds: Mapping[str, float]) -> list[str]:
    chosen = results["retrieval"][results["strategy"]]["hybrid"]
    values = {
        "recall_at_5": chosen["recall_at_5"],
        "mrr": chosen["mrr"],
        "citation_precision": chosen["citation_precision"],
        "answered_with_relevant_citation": results["answers"]["answered_with_relevant_citation"],
        "refusal_on_unanswerable": results["answers"]["refusal_on_unanswerable"],
        "answer_contains_expected": results["answers"]["answer_contains_expected"],
    }
    return [f"{name} {values[name]:.3f} < {limit}" for name, limit in thresholds.items() if values[name] < limit]


def summary(results: Mapping[str, Any]) -> str:
    lines = [f"embeddings: {results['embedding_model']}   chosen strategy: {results['strategy']}", ""]
    lines.append(f"{'strategy':<22}{'chunks':>7}{'mode':>9}{'recall@5':>10}{'MRR':>7}{'cit.prec':>10}{'unans.ctx':>11}")
    for name, per_mode in results["retrieval"].items():
        for mode in MODES:
            m = per_mode[mode]
            lines.append(
                f"{name:<22}{per_mode['chunks']:>7}{mode:>9}{m['recall_at_5']:>10.3f}{m['mrr']:>7.3f}"
                f"{m['citation_precision']:>10.3f}{m['unanswerable_with_context']:>11}"
            )
    a = results["answers"]
    lines += [
        "",
        f"answers: relevant citation {a['answered_with_relevant_citation']:.3f}, contains expected "
        f"{a['answer_contains_expected']:.3f}, refused unanswerable "
        f"{a['refusal_on_unanswerable']:.3f}, model calls {a['model_calls']}, mean tokens in/out "
        f"{a['mean_input_tokens']}/{a['mean_output_tokens']}",
    ]
    if "latency_p50_ms" in a:
        lines.append(
            f"latency per question (retrieve + converse): p50 {a['latency_p50_ms']} ms, p95 {a['latency_p95_ms']} ms,"
            f" max {a['latency_max_ms']} ms"
        )
    return "\n".join(lines)


def run_live(args: argparse.Namespace, config: Mapping[str, Any]) -> dict[str, Any]:  # pragma: no cover - live only
    import boto3  # live path only

    from harbor_rag.aws import CLIENT_CONFIG, Boto3Bedrock  # live path only

    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    port = Boto3Bedrock(
        session.client("bedrock-agent-runtime", config=CLIENT_CONFIG),
        session.client("bedrock-runtime", config=CLIENT_CONFIG),
    )
    golden = load_golden()
    selection = {"max_sources": 3, "min_score": args.min_score, "relative_floor": args.relative_floor}
    results = {
        q.qid: port.retrieve(
            knowledge_base_id=args.kb_id,
            query=q.question,
            number_of_results=config["number_of_results"],
            doc_type=None,
        ).get("retrievalResults", [])
        for q in golden
    }
    settings = Settings(
        knowledge_base_id=args.kb_id,
        model_id=args.model_id,
        guardrail_id=args.guardrail_id,
        guardrail_version=args.guardrail_version,
        min_score=args.min_score,
        relative_floor=args.relative_floor,
    )
    return {
        "embedding_model": "amazon.titan-embed-text-v2:0 (live)",
        "strategy": "live",
        "retrieval": {"live": {"chunks": 0, **{m: score_retrieval(results, golden, selection) for m in MODES}}},
        "answers": score_answers(port, settings, golden, timed=True),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="fail below the thresholds in data/eval.yaml")
    parser.add_argument("--json", type=Path, help="write full results to this file")
    parser.add_argument("--live", action="store_true", help="evaluate the deployed stack (makes AWS calls)")
    for flag in ("--kb-id", "--model-id", "--guardrail-id", "--guardrail-version", "--profile"):
        parser.add_argument(flag)
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--min-score", type=float, default=0.35)
    parser.add_argument("--relative-floor", type=float, default=0.85)
    args = parser.parse_args(argv)
    config = load_config()
    results = run_live(args, config) if args.live else run_offline(config)
    if args.json:
        args.json.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(summary(results))
    if args.check:
        thresholds = {**config["thresholds"], **(config["live_thresholds"] if args.live else {})}
        failures = check(results, thresholds)
        if failures:
            print("FAIL  evaluation below thresholds: " + "; ".join(failures))
            return 1
        print(f"pass  evaluation meets every {'live' if args.live else 'offline'} threshold in data/eval.yaml")
    return 0


if __name__ == "__main__":
    sys.exit(main())
