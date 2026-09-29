"""Embedding fixtures: vectors stored in data/fixtures/embeddings.json so the evaluation never calls a model.

Offline, the vectors come from a deterministic local embedder (signed feature hashing of stemmed words and character
trigrams, 128 dimensions). It is a stand-in with no semantic model behind it, and the report labels its scores as
offline-proxy numbers. `--live` records Amazon Titan Text Embeddings V2 vectors into the same format instead
(maintainer's sandbox account only, see docs/live-test.md).

    python -m harbor_eval.embeddings            # rewrite the fixture file
    python -m harbor_eval.embeddings --check    # fail if it is stale
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from typing import Any

from harbor_eval import DATA
from harbor_eval.chunking import STRATEGIES, chunk_corpus
from harbor_eval.corpus import load
from harbor_eval.golden import load_golden
from harbor_eval.text import terms

FIXTURE = DATA / "fixtures" / "embeddings.json"
DIMS = 128
LOCAL_MODEL = "local-hashed-v1"


def _features(text: str) -> list[str]:
    feats = []
    for term in terms(text):
        feats.append("w:" + term)
        padded = f"#{term}#"
        feats.extend("c:" + padded[i : i + 3] for i in range(len(padded) - 2))
    return feats


def local_embed(text: str, dims: int = DIMS) -> list[float]:
    vector = [0.0] * dims
    for feature in _features(text):
        digest = hashlib.blake2b(feature.encode(), digest_size=8).digest()
        bucket = int.from_bytes(digest[:4], "big") % dims
        sign = 1.0 if digest[4] & 1 else -1.0
        weight = 2.0 if feature.startswith("w:") else 1.0
        vector[bucket] += sign * weight
    norm = math.sqrt(sum(v * v for v in vector)) or 1.0
    return [round(v / norm, 4) for v in vector]


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


def build(embed: Any = local_embed, model: str = LOCAL_MODEL) -> dict[str, Any]:
    docs = load()
    chunks = {
        name: {c.chunk_id: embed(c.search_text) for c in chunk_corpus(docs, strategy)}
        for name, strategy in STRATEGIES.items()
    }
    queries = {q.qid: embed(q.question) for q in load_golden()}
    return {"model": model, "dims": len(next(iter(queries.values()))), "chunks": chunks, "queries": queries}


def load_fixture() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return data


def _serialize(data: dict[str, Any]) -> str:
    return json.dumps(data, separators=(",", ":"), sort_keys=True) + "\n"


def titan_embedder(profile: str | None, region: str) -> Any:  # pragma: no cover - live only
    import boto3  # live path only; not needed offline

    client = boto3.Session(profile_name=profile, region_name=region).client("bedrock-runtime")

    def embed(text: str) -> list[float]:
        body = json.dumps({"inputText": text, "dimensions": 256, "normalize": True})
        response = client.invoke_model(modelId="amazon.titan-embed-text-v2:0", body=body)
        return [round(v, 4) for v in json.loads(response["body"].read())["embedding"]]

    return embed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--live", action="store_true", help="record Titan V2 vectors (makes AWS calls)")
    parser.add_argument("--profile", default=None)
    parser.add_argument("--region", default="us-east-1")
    args = parser.parse_args(argv)
    if args.live:  # pragma: no cover - live only
        out = DATA.parent / ".eval-runs" / "embeddings-titan.json"
        out.parent.mkdir(exist_ok=True)
        out.write_text(_serialize(build(titan_embedder(args.profile, args.region), "amazon.titan-embed-text-v2:0")))
        print(f"wrote {out}")
        return 0
    expected = _serialize(build())
    if args.check:
        if not FIXTURE.exists() or FIXTURE.read_text(encoding="utf-8") != expected:
            print("FAIL  data/fixtures/embeddings.json is stale (run make embeddings)")
            return 1
        print("pass  embedding fixtures match the corpus and golden set")
        return 0
    FIXTURE.write_text(expected, encoding="utf-8")
    print(f"wrote {FIXTURE.relative_to(DATA.parent)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
