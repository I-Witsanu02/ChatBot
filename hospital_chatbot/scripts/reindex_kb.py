#!/usr/bin/env python3
"""Build or rebuild the persistent Chroma index from a JSONL KB.

Default V14 config uses Ollama + bge-m3 for embeddings so runtime and indexing
stay aligned with the user's locally installed models.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

from backend.embedding_factory import EMBEDDING_PROVIDER, build_embedding_function

DEFAULT_KNOWLEDGE = "knowledge.jsonl"
DEFAULT_DB_DIR = "chroma_db"
DEFAULT_COLLECTION = "hospital_faq"
DEFAULT_EMBEDDING_MODEL = "bge-m3:latest"


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Rebuild Chroma KB index")
    p.add_argument("--knowledge", default=DEFAULT_KNOWLEDGE)
    p.add_argument("--db-dir", default=DEFAULT_DB_DIR)
    p.add_argument("--collection", default=DEFAULT_COLLECTION)
    p.add_argument("--embedding-model", default=DEFAULT_EMBEDDING_MODEL)
    p.add_argument("--embedding-provider", default=EMBEDDING_PROVIDER)
    p.add_argument("--reset", action="store_true")
    return p.parse_args()


def sanitize_metadata_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def sanitize_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    return {key: sanitize_metadata_value(value) for key, value in metadata.items()}


def main() -> None:
    args = parse_args()
    knowledge_path = Path(args.knowledge)
    db_dir = Path(args.db_dir)

    import chromadb

    if args.reset and db_dir.exists():
        shutil.rmtree(db_dir)
    db_dir.mkdir(parents=True, exist_ok=True)

    client = chromadb.PersistentClient(path=str(db_dir))
    embedding_fn = build_embedding_function(args.embedding_provider, model_name=args.embedding_model)

    existing = {c.name for c in client.list_collections()}
    if args.collection in existing:
        client.delete_collection(args.collection)

    collection = client.create_collection(name=args.collection, embedding_function=embedding_fn)
    rows = load_jsonl(knowledge_path)

    ids, documents, metadatas = [], [], []
    for row in rows:
        ids.append(str(row["id"]))
        documents.append(
            "\n".join(
                [
                    str(row.get("question", "")),
                    str(row.get("answer", "")),
                    str(row.get("note", "") or row.get("notes", "")),
                    " ".join(str(v) for v in row.get("aliases", []) or []),
                    " ".join(str(v) for v in row.get("keywords", []) or []),
                    str(row.get("subcategory", "")),
                    str(row.get("topic", "")),
                ]
            ).strip()
        )
        metadata = dict(row)
        metadata["requires_clarification"] = bool(row.get("requires_clarification", False))
        metadatas.append(sanitize_metadata(metadata))
    if ids:
        collection.add(ids=ids, documents=documents, metadatas=metadatas)
    print(
        f"Indexed {len(ids)} records into {args.collection} @ {db_dir} "
        f"(embedding_provider={args.embedding_provider}, embedding_model={args.embedding_model})"
    )


if __name__ == "__main__":
    main()
