from __future__ import annotations

import pytest

from harbor_eval import corpus, embeddings
from harbor_eval.chunking import STRATEGIES, Strategy, chunk, chunk_corpus
from harbor_eval.corpus import Document, load
from harbor_eval.evaluate import check, load_config, run_offline
from harbor_eval.golden import load_golden
from harbor_eval.metrics import citation_precision, ranked_docs, recall_at_k, reciprocal_rank
from harbor_eval.offline import extractive_answer
from harbor_eval.retriever import LocalRetriever
from harbor_rag.prompt import NO_ANSWER, Source, build_converse_request


@pytest.fixture(scope="module")
def offline() -> dict:
    return run_offline(load_config())


def test_golden_set_shape() -> None:
    golden = load_golden()
    doc_ids = {d.doc_id for d in load()}
    assert len(golden) == 40
    assert len({q.qid for q in golden}) == 40
    assert sum(not q.answerable for q in golden) == 6
    for q in golden:
        assert set(q.relevant) <= doc_ids, q.qid
        assert bool(q.must_include) == q.answerable


def test_must_include_phrases_are_in_a_relevant_document() -> None:
    texts = {d.doc_id: d.text.lower() for d in load()}
    for q in load_golden():
        for phrase in q.must_include:
            assert any(phrase.lower() in texts[d] for d in q.relevant), (q.qid, phrase)


def test_corpus_has_every_doc_type_and_fresh_sidecars() -> None:
    docs = load()
    assert len(docs) >= 30
    assert {d.doc_type for d in docs} == {"returns", "warranty", "shipping", "supplier", "store-ops"}
    assert corpus.main(["--check"]) == 0


def test_embedding_fixture_is_fresh() -> None:
    assert embeddings.main(["--check"]) == 0


def test_local_embedding_is_deterministic_and_normalized() -> None:
    a = embeddings.local_embed("restocking fee on opened laptops")
    assert a == embeddings.local_embed("restocking fee on opened laptops")
    assert abs(sum(v * v for v in a) - 1) < 1e-3
    assert embeddings.cosine(a, a) == pytest.approx(1, abs=1e-3)


def test_metrics() -> None:
    ranked = ranked_docs(["a", "a", "b", "c"])
    assert ranked == ["a", "b", "c"]
    assert recall_at_k(ranked, ["b", "z"], 2) == 0.5
    assert reciprocal_rank(ranked, ["c"]) == pytest.approx(1 / 3)
    assert reciprocal_rank(ranked, ["z"]) == 0
    assert citation_precision(["a", "b"], ["a"]) == 0.5
    assert citation_precision([], ["a"]) == 0
    with pytest.raises(ValueError, match="undefined"):
        recall_at_k(ranked, [], 5)


def doc(words: int) -> Document:
    return Document("returns-x", "X", "returns", " ".join(f"w{i}" for i in range(words)))


def test_fixed_chunks_overlap_and_cover_the_document() -> None:
    chunks = chunk(doc(250), Strategy("f", "fixed", 100, 0.2))
    assert [len(c.text.split()) for c in chunks] == [100, 100, 90]
    assert chunks[1].text.split()[0] == "w80"
    assert chunks[-1].text.split()[-1] == "w249"


def test_hierarchical_chunks_search_children_and_return_the_parent() -> None:
    chunks = chunk(doc(120), STRATEGIES["hierarchical-300-60"])
    assert len(chunks) == 2
    assert all(c.text == doc(120).text for c in chunks)
    assert chunks[0].search_text != chunks[1].search_text


def test_retriever_returns_the_retrieve_shape_and_honors_doc_type() -> None:
    docs = load()
    strategy = STRATEGIES["fixed-100"]
    chunks = chunk_corpus(docs, strategy)
    vectors = {c.chunk_id: embeddings.local_embed(c.search_text) for c in chunks}
    retriever = LocalRetriever(chunks, vectors)
    query = "restocking fee opened laptop"
    out = retriever.retrieve(query, embeddings.local_embed(query), 5, doc_type="returns")["retrievalResults"]
    assert len(out) == 5
    assert all(r["metadata"]["doc_type"] == "returns" for r in out)
    assert out[0]["metadata"]["doc_id"] == "returns-opened-electronics"
    assert all(0 <= r["score"] <= 1 for r in out)
    with pytest.raises(ValueError, match="bogus"):
        LocalRetriever(chunks, vectors, "bogus")


def test_extractive_stand_in_cites_or_declines() -> None:
    sources = [Source(1, "s3://b/r.md", "Returns", "returns", "Customers may return items within 30 days.", 0.9)]
    request = build_converse_request(
        question="How many days to return items?",
        sources=sources,
        model_id="m",
        guardrail_id="g",
        guardrail_version="1",
        max_output_tokens=100,
    )
    answer = extractive_answer(request)["output"]["message"]["content"][0]["text"]
    assert answer.endswith("[1]")
    assert "30 days" in answer
    request = build_converse_request(
        question="Forklift dress code?",
        sources=sources,
        model_id="m",
        guardrail_id="g",
        guardrail_version="1",
        max_output_tokens=100,
    )
    assert extractive_answer(request)["output"]["message"]["content"][0]["text"] == NO_ANSWER


def test_offline_evaluation_meets_the_thresholds(offline: dict) -> None:
    assert check(offline, load_config()["thresholds"]) == []


def test_unanswerable_questions_never_reach_an_answer(offline: dict) -> None:
    rows = [r for r in offline["answers"]["questions"] if "refused" in r]
    assert len(rows) == 6
    assert all(r["refused"] for r in rows)


def test_live_threshold_gates_answer_content(offline: dict) -> None:
    config = load_config()
    failures = check(offline, {**config["thresholds"], **config["live_thresholds"]})
    assert [f.split()[0] for f in failures] == ["answer_contains_expected"]


def test_threshold_check_reports_regressions(offline: dict) -> None:
    thresholds = {**load_config()["thresholds"], "recall_at_5": 1.01}
    failures = check(offline, thresholds)
    assert len(failures) == 1
    assert failures[0].startswith("recall_at_5")
