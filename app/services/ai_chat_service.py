"""RAG-based AI chatbot service using MongoDB Atlas Vector Search and Mistral API."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

import asyncio
import httpx
import json
import math
import time

from app.core.config import settings
from app.core.database import get_database


class ChatServiceError(Exception):
    """Base exception for chatbot service errors."""


class MissingAIConfigError(ChatServiceError):
    """Raised when required AI configuration or secrets are missing."""


# region agent log
def _debug_log(message: str, data: Dict[str, Any], hypothesis_id: str, run_id: str = "initial") -> None:
    """
    Append a single NDJSON debug line to the shared debug log.

    NOTE: Do NOT log secrets (API keys, passwords, tokens, PII).
    """
    payload = {
        "id": f"log_{int(time.time() * 1000)}",
        "timestamp": int(time.time() * 1000),
        "location": "app/services/ai_chat_service.py",
        "message": message,
        "data": data,
        "runId": run_id,
        "hypothesisId": hypothesis_id,
    }
    try:
        with open(r"c:\FastApi\.cursor\debug.log", "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        # Swallow all logging errors to avoid impacting runtime behavior.
        pass


# endregion


async def _get_knowledge_collection():
    """
    Returns the MongoDB collection used for RAG knowledge.

    Collection name is hard-coded for now; adjust if you change the schema.
    """
    db = await get_database()
    return db[settings.KNOWLEDGE_BASE_COLLECTION]


def _cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """Compute cosine similarity between two vectors of equal length."""
    if len(a) != len(b):
        return -1.0
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for x, y in zip(a, b):
        xf = float(x)
        yf = float(y)
        dot += xf * yf
        norm_a += xf * xf
        norm_b += yf * yf
    if norm_a <= 0.0 or norm_b <= 0.0:
        return -1.0
    return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))


async def embed_texts(texts: Sequence[str]) -> List[List[float]]:
    """
    Generate embeddings for a list of texts using Mistral's embeddings endpoint.

    Uses:
      POST {MISTRAL_API_BASE}/v1/embeddings
      Body: { "model": EMBEDDING_MODEL, "input": [...] }
    """
    if not texts:
        return []

    if not settings.MISTRAL_API_KEY:
        raise MissingAIConfigError("MISTRAL_API_KEY is not configured.")

    if not settings.EMBEDDING_MODEL:
        raise MissingAIConfigError("EMBEDDING_MODEL is not configured.")

    url = f"{settings.MISTRAL_API_BASE.rstrip('/')}/v1/embeddings"
    headers = {
        "Authorization": f"Bearer {settings.MISTRAL_API_KEY}",
        "Content-Type": "application/json",
    }
    input_texts = list(texts)
    batch_size = max(1, int(settings.EMBEDDING_BATCH_SIZE))
    embeddings: List[List[float]] = []

    async with httpx.AsyncClient(timeout=30.0) as client:
        max_retries = max(0, int(settings.MISTRAL_MAX_RETRIES))
        base_delay = max(0.1, float(settings.MISTRAL_RETRY_BASE_SECONDS))
        max_delay = max(base_delay, float(settings.MISTRAL_RETRY_MAX_SECONDS))

        for batch_start in range(0, len(input_texts), batch_size):
            batch = input_texts[batch_start : batch_start + batch_size]
            payload: Dict[str, Any] = {
                "model": settings.EMBEDDING_MODEL,
                "input": batch,
                # Encoding format defaults to float; no need to override.
            }

            resp: Optional[httpx.Response] = None
            last_error: Optional[Exception] = None
            for attempt in range(max_retries + 1):
                try:
                    resp = await client.post(url, headers=headers, json=payload)
                    if resp.status_code == 429:
                        retry_after_header = resp.headers.get("Retry-After")
                        retry_after: Optional[float] = None
                        if retry_after_header:
                            try:
                                retry_after = float(retry_after_header)
                            except ValueError:
                                retry_after = None

                        if attempt >= max_retries:
                            resp.raise_for_status()

                        backoff = min(max_delay, base_delay * (2**attempt))
                        wait_seconds = retry_after if retry_after and retry_after > 0 else backoff
                        _debug_log(
                            message="embed_texts rate limited; retrying",
                            data={
                                "status_code": 429,
                                "attempt": attempt + 1,
                                "max_attempts": max_retries + 1,
                                "wait_seconds": wait_seconds,
                                "batch_start": batch_start,
                                "batch_size": len(batch),
                            },
                            hypothesis_id="H1",
                        )
                        await asyncio.sleep(wait_seconds)
                        continue

                    # Retry transient upstream issues.
                    if 500 <= resp.status_code < 600 and attempt < max_retries:
                        backoff = min(max_delay, base_delay * (2**attempt))
                        _debug_log(
                            message="embed_texts upstream error; retrying",
                            data={
                                "status_code": resp.status_code,
                                "attempt": attempt + 1,
                                "max_attempts": max_retries + 1,
                                "wait_seconds": backoff,
                                "batch_start": batch_start,
                                "batch_size": len(batch),
                            },
                            hypothesis_id="H1",
                        )
                        await asyncio.sleep(backoff)
                        continue

                    resp.raise_for_status()
                    break
                except (httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError) as exc:
                    last_error = exc
                    if attempt >= max_retries:
                        raise ChatServiceError(f"Error calling Mistral embeddings API: {exc}") from exc
                    backoff = min(max_delay, base_delay * (2**attempt))
                    _debug_log(
                        message="embed_texts network error; retrying",
                        data={
                            "error_type": type(exc).__name__,
                            "attempt": attempt + 1,
                            "max_attempts": max_retries + 1,
                            "wait_seconds": backoff,
                            "batch_start": batch_start,
                            "batch_size": len(batch),
                        },
                        hypothesis_id="H1",
                    )
                    await asyncio.sleep(backoff)
                except httpx.HTTPError as exc:
                    raise ChatServiceError(f"Error calling Mistral embeddings API: {exc}") from exc

            if resp is None:
                if last_error is not None:
                    raise ChatServiceError(f"Error calling Mistral embeddings API: {last_error}") from last_error
                raise ChatServiceError("Error calling Mistral embeddings API: request failed without response.")

            data = resp.json()
            for item in data.get("data", []):
                emb = item.get("embedding")
                if isinstance(emb, list):
                    embeddings.append(emb)

    if not embeddings:
        raise ChatServiceError("Mistral embeddings API returned no embeddings.")
    if len(embeddings) != len(input_texts):
        raise ChatServiceError(
            f"Mistral embeddings API returned {len(embeddings)} embeddings for {len(input_texts)} inputs."
        )

    # Optional sanity check: ensure embedding dimensions match config if provided.
    if settings.EMBEDDING_DIMENSIONS is not None:
        dim = len(embeddings[0])
        if dim != settings.EMBEDDING_DIMENSIONS:
            raise ChatServiceError(
                f"Embedding dimension {dim} does not match configured EMBEDDING_DIMENSIONS "
                f"{settings.EMBEDDING_DIMENSIONS}. Ensure Atlas index and model configuration align."
            )

    # region agent log
    _debug_log(
        message="embed_texts completed",
        data={
            "input_count": len(texts),
            "first_input_length": len(texts[0]) if texts else 0,
            "embeddings_count": len(embeddings),
            "embedding_dimension": len(embeddings[0]) if embeddings else None,
        },
        hypothesis_id="H1",
    )
    # endregion

    return embeddings


async def vector_search_knowledge(
    query_embedding: List[float],
    limit: int = 5,
    num_candidates: int = 100,
) -> List[Dict[str, Any]]:
    """
    Perform a vector search over the KnowledgeBase collection using Atlas Vector Search.

    Expects an Atlas vector index on the `embedding` field, for example:
      {
        "fields": [
          {
            "type": "vector",
            "path": "embedding",
            "numDimensions": <EMBEDDING_DIMENSIONS>,
            "similarity": "cosine"
          }
        ]
      }
    """
    if not query_embedding:
        return []

    collection = await _get_knowledge_collection()
    vector_index_name = settings.KNOWLEDGE_VECTOR_INDEX_NAME

    # Prefer Atlas Vector Search when an index is available.
    has_vector_index = False
    available_indexes: List[str] = []
    try:
        async for idx in collection.list_search_indexes():
            idx_name = idx.get("name")
            if isinstance(idx_name, str):
                available_indexes.append(idx_name)
        has_vector_index = vector_index_name in available_indexes
    except Exception:
        # If listing indexes is unavailable in the current environment, try query path.
        has_vector_index = True

    results: List[Dict[str, Any]]
    if has_vector_index:
        pipeline = [
            {
                "$vectorSearch": {
                    "index": vector_index_name,
                    "path": "embedding",
                    "queryVector": query_embedding,
                    "numCandidates": num_candidates,
                    "limit": limit,
                }
            },
            {
                "$project": {
                    "text": 1,
                    "metadata": 1,
                    "score": {"$meta": "vectorSearchScore"},
                }
            },
        ]
        try:
            results = await collection.aggregate(pipeline).to_list(length=limit)
        except Exception:
            # Fall back to brute-force cosine similarity if Atlas vector search fails.
            results = []
    else:
        results = []

    # Fallback path: in-app cosine similarity over stored embeddings.
    if not results:
        docs = await collection.find(
            {"embedding": {"$type": "array"}},
            {"text": 1, "metadata": 1, "embedding": 1},
        ).to_list(length=None)

        scored: List[Dict[str, Any]] = []
        for doc in docs:
            emb = doc.get("embedding")
            if not isinstance(emb, list):
                continue
            score = _cosine_similarity(query_embedding, emb)
            if score < -0.5:
                continue
            scored.append(
                {
                    "_id": doc.get("_id"),
                    "text": doc.get("text"),
                    "metadata": doc.get("metadata"),
                    "score": score,
                }
            )
        scored.sort(key=lambda d: d.get("score", -1.0), reverse=True)
        results = scored[:limit]

    # region agent log
    _debug_log(
        message="vector_search_knowledge results",
        data={
            "results_count": len(results),
            "limit": limit,
            "num_candidates": num_candidates,
            "vector_index": vector_index_name,
            "available_indexes": available_indexes,
        },
        hypothesis_id="H1",
    )
    # endregion

    return results


def _build_context_from_results(results: Sequence[Dict[str, Any]]) -> Tuple[str, List[Dict[str, Any]]]:
    """
    Build a plain-text context string and a list of lightweight source dicts
    from vector search results.
    """
    context_chunks: List[str] = []
    sources: List[Dict[str, Any]] = []

    for doc in results:
        text = doc.get("text") or ""
        metadata = doc.get("metadata") or {}

        if not isinstance(text, str) or not text.strip():
            continue

        context_chunks.append(text.strip())

        source = metadata.get("source")
        score = doc.get("score") or doc.get("_score")
        source_entry: Dict[str, Any] = {
            "text": text,
            "source": source or str(doc.get("_id", "")),
        }
        if isinstance(score, (int, float)):
            source_entry["score"] = float(score)

        sources.append(source_entry)

    # region agent log
    _debug_log(
        message="build_context_from_results",
        data={
            "raw_results": len(results),
            "used_docs": len(sources),
            "context_length": sum(len(c) for c in context_chunks),
        },
        hypothesis_id="H4",
    )
    # endregion

    context = "\n\n---\n\n".join(context_chunks)
    return context, sources


async def call_mistral_chat(
    question: str,
    context: str,
    history: Optional[Sequence[Dict[str, str]]] = None,
) -> str:
    """
    Call Mistral's chat completion endpoint with a RAG-style prompt.

    Uses:
      POST {MISTRAL_API_BASE}/v1/chat/completions
      Body: { "model": MISTRAL_MODEL, "messages": [...], "temperature": 0.2 }
    """
    if not settings.MISTRAL_API_KEY:
        raise MissingAIConfigError("MISTRAL_API_KEY is not configured.")

    if not settings.MISTRAL_MODEL:
        raise MissingAIConfigError("MISTRAL_MODEL is not configured.")

    url = f"{settings.MISTRAL_API_BASE.rstrip('/')}/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.MISTRAL_API_KEY}",
        "Content-Type": "application/json",
    }

    system_content = (
        "You are an assistant for a student enrollment and credit management system.\n"
        "Use ONLY the context below to answer the user's question.\n"
        "If the answer is not in the context, say you don't know.\n\n"
        f"Context:\n{context or '[no context retrieved]'}"
    )

    messages: List[Dict[str, str]] = [
        {"role": "system", "content": system_content},
    ]

    # Append prior conversation history if provided (must already use user/assistant/system roles).
    if history:
        for msg in history:
            role = msg.get("role")
            content = msg.get("content")
            if role in {"user", "assistant", "system"} and isinstance(content, str):
                messages.append({"role": role, "content": content})

    messages.append({"role": "user", "content": question})

    payload: Dict[str, Any] = {
        "model": settings.MISTRAL_MODEL,
        "messages": messages,
        "temperature": 0.2,
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise ChatServiceError(f"Error calling Mistral chat API: {exc}") from exc

    data = resp.json()
    choices = data.get("choices") or []
    if not choices:
        raise ChatServiceError("Mistral chat API returned no choices.")

    message = choices[0].get("message") or {}
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ChatServiceError("Mistral chat API returned an empty response.")

    return content.strip()


async def chat_with_rag(
    question: str,
    history: Optional[Sequence[Dict[str, str]]] = None,
) -> Tuple[str, List[Dict[str, Any]]]:
    """
    High-level entry point for the chatbot:

    1. Embed the user's question.
    2. Run vector search on KnowledgeBase.
    3. Build a context string from top results.
    4. Call Mistral chat completion with that context.

    Returns:
        (answer_text, sources_list)
    """
    # region agent log
    _debug_log(
        message="chat_with_rag called",
        data={
            "question_length": len(question),
            "question_preview": question[:100],
        },
        hypothesis_id="H1",
    )
    # endregion

    # 1. Embed question
    embeddings = await embed_texts([question])
    query_embedding = embeddings[0]

    # 2. Vector search in MongoDB Atlas
    results = await vector_search_knowledge(query_embedding=query_embedding, limit=5, num_candidates=100)

    # 3. Build context and source metadata
    context, sources = _build_context_from_results(results)

    # 4. Call Mistral chat
    answer = await call_mistral_chat(question=question, context=context, history=history)

    return answer, sources
