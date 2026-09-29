"""The fixture corpus in data/corpus and its Bedrock metadata sidecar files.

Each `<doc>.md` gets a `<doc>.md.metadata.json` next to it, the format Bedrock Knowledge Bases reads from S3 for
metadata filtering. The sidecars are generated from the file name and the first heading, and `--check` fails when one
is missing or stale.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from harbor_eval import DATA

CORPUS = DATA / "corpus"
BUCKET_URI = "s3://harbor-goods-policies-111122223333"
PREFIX_TO_TYPE = {
    "returns": "returns",
    "warranty": "warranty",
    "shipping": "shipping",
    "supplier": "supplier",
    "store": "store-ops",
}


@dataclass(frozen=True)
class Document:
    doc_id: str
    title: str
    doc_type: str
    text: str

    @property
    def uri(self) -> str:
        return f"{BUCKET_URI}/{self.doc_type}/{self.doc_id}.md"


def doc_type_of(doc_id: str) -> str:
    return PREFIX_TO_TYPE[doc_id.split("-", 1)[0]]


def load(corpus: Path = CORPUS) -> list[Document]:
    docs = []
    for path in sorted(corpus.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        title = next(line[2:].strip() for line in text.splitlines() if line.startswith("# "))
        docs.append(Document(doc_id=path.stem, title=title, doc_type=doc_type_of(path.stem), text=text))
    return docs


def sidecar(doc: Document) -> str:
    body = {"metadataAttributes": {"doc_type": doc.doc_type, "title": doc.title, "doc_id": doc.doc_id}}
    return json.dumps(body, indent=2) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if a sidecar is missing or stale")
    parser.add_argument("--upload-plan", action="store_true", help="print '<local path> <S3 key>' lines to upload")
    args = parser.parse_args(argv)
    if args.upload_plan:
        for doc in load():
            key = doc.uri.removeprefix(BUCKET_URI + "/")
            print(f"{CORPUS / (doc.doc_id + '.md')} {key}")
            print(f"{CORPUS / (doc.doc_id + '.md.metadata.json')} {key}.metadata.json")
        return 0
    stale = []
    for doc in load():
        path = CORPUS / f"{doc.doc_id}.md.metadata.json"
        expected = sidecar(doc)
        if not path.exists() or path.read_text(encoding="utf-8") != expected:
            stale.append(path.name)
            if not args.check:
                path.write_text(expected, encoding="utf-8")
    orphans = [
        p.name for p in CORPUS.glob("*.metadata.json") if not (CORPUS / p.name.removesuffix(".metadata.json")).exists()
    ]
    if args.check and (stale or orphans):
        print(f"FAIL  corpus metadata out of date: {', '.join(stale + orphans)} (run make corpus-metadata)")
        return 1
    print(f"pass  corpus metadata for {len(load())} documents")
    return 0


if __name__ == "__main__":
    sys.exit(main())
