"""
Re-embed existing KnowledgeBase documents with Gemini embeddings.

Usage (from Backend/ directory):

    python -m scripts.reembed_knowledge_base --dry-run
    python -m scripts.reembed_knowledge_base
    python -m scripts.reembed_knowledge_base --limit 100
"""

from __future__ import annotations

import argparse
import asyncio
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.core.database import get_database
from app.services.ai_chat_service import embed_texts


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Re-embed KnowledgeBase with Gemini embeddings.")
    parser.add_argument("--dry-run", action="store_true", help="Only report what would be updated.")
    parser.add_argument("--limit", type=int, default=None, help="Maximum number of docs to process.")
    return parser.parse_args()


async def run(dry_run: bool, limit: Optional[int]) -> None:
    db = await get_database()
    collection = db[settings.KNOWLEDGE_BASE_COLLECTION]

    query: Dict[str, Any] = {"text": {"$type": "string", "$ne": ""}}
    total_docs = await collection.count_documents(query)
    if limit is not None:
        total_docs = min(total_docs, max(0, limit))

    print(f"[reembed] Collection: {settings.KNOWLEDGE_BASE_COLLECTION}")
    print(f"[reembed] Target docs: {total_docs}")
    print(f"[reembed] Dry run: {dry_run}")
    print(f"[reembed] Embedding model: {settings.GEMINI_EMBEDDING_MODEL}")
    print(f"[reembed] Embedding dimensions: {settings.EMBEDDING_DIMENSIONS}")
    print(f"[reembed] Batch size: {settings.EMBEDDING_BATCH_SIZE}")

    if total_docs == 0:
        print("[reembed] No eligible documents found.")
        return

    if dry_run:
        print("[reembed] Dry run complete. No updates were made.")
        return

    processed = 0
    updated = 0
    failed_ids: List[str] = []
    batch_size = max(1, int(settings.EMBEDDING_BATCH_SIZE))

    cursor = collection.find(query, {"text": 1, "metadata": 1}).sort("_id", 1)
    if limit is not None and limit > 0:
        cursor = cursor.limit(limit)

    batch_docs: List[Dict[str, Any]] = []
    async for doc in cursor:
        batch_docs.append(doc)
        if len(batch_docs) < batch_size:
            continue

        texts = [d.get("text", "") for d in batch_docs]
        try:
            vectors = await embed_texts(texts, task_type="RETRIEVAL_DOCUMENT")
            for d, vec in zip(batch_docs, vectors):
                existing_metadata = d.get("metadata")
                metadata = dict(existing_metadata) if isinstance(existing_metadata, dict) else {}
                metadata["embedding_provider"] = "gemini"
                metadata["embedding_model"] = settings.GEMINI_EMBEDDING_MODEL
                metadata["embedding_dimensions"] = settings.EMBEDDING_DIMENSIONS

                result = await collection.update_one(
                    {"_id": d["_id"]},
                    {"$set": {"embedding": vec, "metadata": metadata}},
                )
                updated += result.modified_count
        except Exception:
            failed_ids.extend(str(d.get("_id")) for d in batch_docs)

        processed += len(batch_docs)
        print(f"[reembed] Processed {processed}/{total_docs}")
        batch_docs = []

    if batch_docs:
        texts = [d.get("text", "") for d in batch_docs]
        try:
            vectors = await embed_texts(texts, task_type="RETRIEVAL_DOCUMENT")
            for d, vec in zip(batch_docs, vectors):
                existing_metadata = d.get("metadata")
                metadata = dict(existing_metadata) if isinstance(existing_metadata, dict) else {}
                metadata["embedding_provider"] = "gemini"
                metadata["embedding_model"] = settings.GEMINI_EMBEDDING_MODEL
                metadata["embedding_dimensions"] = settings.EMBEDDING_DIMENSIONS

                result = await collection.update_one(
                    {"_id": d["_id"]},
                    {"$set": {"embedding": vec, "metadata": metadata}},
                )
                updated += result.modified_count
        except Exception:
            failed_ids.extend(str(d.get("_id")) for d in batch_docs)

        processed += len(batch_docs)
        print(f"[reembed] Processed {processed}/{total_docs}")

    print(f"[reembed] Completed. Processed: {processed}, Updated: {updated}, Failed: {len(failed_ids)}")
    if failed_ids:
        print(f"[reembed] Failed _ids: {', '.join(failed_ids)}")


if __name__ == "__main__":
    args = parse_args()
    asyncio.run(run(dry_run=args.dry_run, limit=args.limit))
