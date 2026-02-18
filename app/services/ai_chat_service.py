"""RAG-based AI chatbot service using MongoDB Atlas Vector Search and Gemini API."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

import asyncio
import hashlib
import httpx
import json
import math
import re
import time

from app.core.config import settings
from app.core.database import get_database
from app.services.ai_context_service import (
    build_domain_context,
    build_realtime_context,
    build_user_context,
    serialize_context_for_prompt,
)


class ChatServiceError(Exception):
    """Base exception for chatbot service errors."""


class MissingAIConfigError(ChatServiceError):
    """Raised when required AI configuration or secrets are missing."""


class RateLimitedAIError(ChatServiceError):
    """Raised when upstream AI provider is rate-limiting requests."""


_GEMINI_REQUEST_SEMAPHORE = asyncio.Semaphore(max(1, int(settings.GEMINI_MAX_CONCURRENT_REQUESTS)))
_GEMINI_THROTTLE_LOCK = asyncio.Lock()
_LAST_GEMINI_REQUEST_TS = 0.0
_EMBED_CACHE_TTL_SECONDS = 180.0
_CHAT_CACHE_TTL_SECONDS = 90.0
_CACHE_MAX_ITEMS = 512
_EMBED_CACHE: Dict[str, Tuple[float, List[float]]] = {}
_CHAT_CACHE: Dict[str, Tuple[float, str]] = {}
_EMBED_INFLIGHT: Dict[str, asyncio.Future] = {}
_CHAT_INFLIGHT: Dict[str, asyncio.Future] = {}
_EMBED_CACHE_LOCK = asyncio.Lock()
_CHAT_CACHE_LOCK = asyncio.Lock()


async def _throttle_gemini_request_rate() -> None:
    """Process-local throttle to reduce bursty provider 429s."""
    global _LAST_GEMINI_REQUEST_TS

    min_interval = max(0.0, float(settings.GEMINI_MIN_REQUEST_INTERVAL_SECONDS))
    if min_interval <= 0.0:
        return

    async with _GEMINI_THROTTLE_LOCK:
        now = time.monotonic()
        elapsed = now - _LAST_GEMINI_REQUEST_TS
        if elapsed < min_interval:
            await asyncio.sleep(min_interval - elapsed)
        _LAST_GEMINI_REQUEST_TS = time.monotonic()


def _make_cache_key(payload: Dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _prune_cache_if_needed(cache: Dict[str, Tuple[float, Any]]) -> None:
    if len(cache) <= _CACHE_MAX_ITEMS:
        return
    now = time.time()
    stale_keys = [k for k, (exp, _) in cache.items() if exp <= now]
    for k in stale_keys:
        cache.pop(k, None)
    if len(cache) <= _CACHE_MAX_ITEMS:
        return
    # Trim oldest expirations to keep memory bounded.
    keys_by_exp = sorted(cache.items(), key=lambda item: item[1][0])
    for key, _ in keys_by_exp[: max(1, len(cache) - _CACHE_MAX_ITEMS)]:
        cache.pop(key, None)


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


async def embed_texts(
    texts: Sequence[str],
    task_type: str = "RETRIEVAL_DOCUMENT",
) -> List[List[float]]:
    """
    Generate embeddings for a list of texts using Gemini's embeddings endpoint.

    Uses:
      POST {GEMINI_API_BASE}/models/{model}:batchEmbedContents
    """
    if not texts:
        return []

    if not settings.GEMINI_API_KEY:
        raise MissingAIConfigError("GEMINI_API_KEY is not configured.")

    if not settings.GEMINI_EMBEDDING_MODEL:
        raise MissingAIConfigError("GEMINI_EMBEDDING_MODEL is not configured.")

    # Dedupe/cache only for single-text requests (runtime query path).
    embed_cache_key: Optional[str] = None
    inflight_future: Optional[asyncio.Future] = None
    is_embed_owner = False
    if len(texts) == 1:
        embed_cache_key = _make_cache_key(
            {
                "type": "embed",
                "task_type": task_type,
                "text": texts[0],
                "model": settings.GEMINI_EMBEDDING_MODEL,
                "dim": settings.EMBEDDING_DIMENSIONS,
            }
        )
        now = time.time()
        async with _EMBED_CACHE_LOCK:
            cached = _EMBED_CACHE.get(embed_cache_key)
            if cached and cached[0] > now:
                _debug_log(
                    message="embed_texts cache hit",
                    data={"task_type": task_type},
                    hypothesis_id="H1",
                )
                return [cached[1]]
            inflight_future = _EMBED_INFLIGHT.get(embed_cache_key)
            if inflight_future is None:
                loop = asyncio.get_running_loop()
                inflight_future = loop.create_future()
                _EMBED_INFLIGHT[embed_cache_key] = inflight_future
                is_embed_owner = True

    if embed_cache_key and inflight_future and not is_embed_owner:
        # Another request is already computing this embedding; await it.
        result = await inflight_future
        return [result]

    model_name = settings.GEMINI_EMBEDDING_MODEL
    model_path = model_name if model_name.startswith("models/") else f"models/{model_name}"
    url = f"{settings.GEMINI_API_BASE.rstrip('/')}/{model_path}:batchEmbedContents"
    headers = {
        "x-goog-api-key": settings.GEMINI_API_KEY,
        "Content-Type": "application/json",
    }
    input_texts = list(texts)
    batch_size = max(1, int(settings.EMBEDDING_BATCH_SIZE))
    embeddings: List[List[float]] = []

    async with httpx.AsyncClient(timeout=30.0) as client:
        max_retries = max(0, int(settings.GEMINI_MAX_RETRIES))
        base_delay = max(0.1, float(settings.GEMINI_RETRY_BASE_SECONDS))
        max_delay = max(base_delay, float(settings.GEMINI_RETRY_MAX_SECONDS))

        try:
            for batch_start in range(0, len(input_texts), batch_size):
                batch = input_texts[batch_start : batch_start + batch_size]
                payload: Dict[str, Any] = {
                    "requests": [
                        {
                            "model": model_path,
                            "content": {"parts": [{"text": text}]},
                            "outputDimensionality": settings.EMBEDDING_DIMENSIONS,
                            "taskType": task_type,
                        }
                        for text in batch
                    ]
                }

                resp: Optional[httpx.Response] = None
                last_error: Optional[Exception] = None
                for attempt in range(max_retries + 1):
                    try:
                        async with _GEMINI_REQUEST_SEMAPHORE:
                            await _throttle_gemini_request_rate()
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
                            raise ChatServiceError(f"Error calling Gemini embeddings API: {exc}") from exc
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
                        raise ChatServiceError(f"Error calling Gemini embeddings API: {exc}") from exc

                if resp is None:
                    if last_error is not None:
                        raise ChatServiceError(f"Error calling Gemini embeddings API: {last_error}") from last_error
                    raise ChatServiceError("Error calling Gemini embeddings API: request failed without response.")

                data = resp.json()
                for item in data.get("data", []):
                    emb = None
                    if isinstance(item, dict):
                        emb = item.get("values")
                        if emb is None:
                            emb_obj = item.get("embedding")
                            if isinstance(emb_obj, dict):
                                emb = emb_obj.get("values")
                    if isinstance(emb, list):
                        embeddings.append(emb)
                if not data.get("data"):
                    for item in data.get("embeddings", []):
                        emb = item.get("values") if isinstance(item, dict) else None
                        if isinstance(emb, list):
                            embeddings.append(emb)
        except Exception as exc:
            if embed_cache_key:
                async with _EMBED_CACHE_LOCK:
                    inflight = _EMBED_INFLIGHT.pop(embed_cache_key, None)
                    if inflight and not inflight.done():
                        inflight.set_exception(exc)
            raise

    if not embeddings:
        raise ChatServiceError("Gemini embeddings API returned no embeddings.")
    if len(embeddings) != len(input_texts):
        raise ChatServiceError(
            f"Gemini embeddings API returned {len(embeddings)} embeddings for {len(input_texts)} inputs."
        )

    # Optional sanity check: ensure embedding dimensions match config if provided.
    if settings.EMBEDDING_DIMENSIONS is not None:
        dim = len(embeddings[0])
        if dim != settings.EMBEDDING_DIMENSIONS:
            raise ChatServiceError(
                f"Embedding dimension {dim} does not match configured EMBEDDING_DIMENSIONS "
                f"{settings.EMBEDDING_DIMENSIONS}. Ensure Atlas index and model configuration align."
            )

    if embed_cache_key:
        async with _EMBED_CACHE_LOCK:
            _EMBED_CACHE[embed_cache_key] = (time.time() + _EMBED_CACHE_TTL_SECONDS, embeddings[0])
            _prune_cache_if_needed(_EMBED_CACHE)
            inflight = _EMBED_INFLIGHT.pop(embed_cache_key, None)
            if inflight and not inflight.done():
                inflight.set_result(embeddings[0])

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
    score_threshold: Optional[float] = None,
    metadata_filter: Optional[Dict[str, Any]] = None,
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
                **({"filter": metadata_filter} if metadata_filter else {}),
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
        fallback_query: Dict[str, Any] = {"embedding": {"$type": "array"}}
        docs = await collection.find(
            fallback_query,
            {"text": 1, "metadata": 1, "embedding": 1},
        ).to_list(length=None)

        scored: List[Dict[str, Any]] = []
        for doc in docs:
            if metadata_filter:
                allowed = True
                for k, v in metadata_filter.items():
                    parts = k.split(".")
                    val: Any = doc
                    for p in parts:
                        if isinstance(val, dict) and p in val:
                            val = val[p]
                        else:
                            val = None
                            break
                    if val != v:
                        allowed = False
                        break
                if not allowed:
                    continue
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

    if score_threshold is not None:
        results = [r for r in results if isinstance(r.get("score"), (int, float)) and float(r["score"]) >= score_threshold]

    # region agent log
    _debug_log(
        message="vector_search_knowledge results",
        data={
            "results_count": len(results),
            "limit": limit,
            "num_candidates": num_candidates,
            "vector_index": vector_index_name,
            "available_indexes": available_indexes,
            "score_threshold": score_threshold,
            "has_metadata_filter": bool(metadata_filter),
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
    seen_pairs: set[tuple[str, str]] = set()

    for doc in results:
        text = doc.get("text") or ""
        metadata = doc.get("metadata") or {}

        if not isinstance(text, str) or not text.strip():
            continue

        source = str(metadata.get("source") or doc.get("_id") or "").strip() or "unknown"
        program_type = str(metadata.get("program_type") or "").strip()
        chunk_idx = metadata.get("chunk_index")
        chunk_total = metadata.get("chunk_total")
        dedupe_key = (source, text.strip())
        if dedupe_key in seen_pairs:
            continue
        seen_pairs.add(dedupe_key)

        chunk_label_parts = [f"Source: {source}"]
        if program_type:
            chunk_label_parts.append(f"Program: {program_type}")
        if isinstance(chunk_idx, int) and isinstance(chunk_total, int):
            chunk_label_parts.append(f"Chunk: {chunk_idx + 1}/{chunk_total}")
        context_chunks.append(f"[{' | '.join(chunk_label_parts)}]\n{text.strip()}")

        score = doc.get("score") or doc.get("_score")
        source_entry: Dict[str, Any] = {
            "text": text,
            "source": source,
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


def _detect_program_type_from_year_label(value: Any) -> Optional[str]:
    label = str(value or "").strip().lower()
    if not label:
        return None
    if re.search(r"\b5(th)?\s*year\b", label) or "5year" in label or "five year" in label:
        return "5year"
    if re.search(r"\b4(th)?\s*year\b", label) or "4year" in label or "four year" in label:
        return "4year"
    return None


def _normalize_program_type(value: Any) -> Optional[str]:
    text = str(value or "").strip().lower().replace(" ", "").replace("-", "")
    if not text:
        return None
    if text in {"5year", "5years", "fiveyear", "program5year", "year5"}:
        return "5year"
    if text in {"4year", "4years", "fouryear", "program4year", "year4"}:
        return "4year"
    if "5year" in text or "fiveyear" in text:
        return "5year"
    if "4year" in text or "fouryear" in text:
        return "4year"
    return None


def _program_type_from_text(question: str) -> Optional[str]:
    q = (question or "").lower()
    if re.search(r"\b5\s*[- ]?year\b", q) or "fifth year" in q:
        return "5year"
    if re.search(r"\b4\s*[- ]?year\b", q) or "fourth year" in q:
        return "4year"
    return None


def _resolve_program_type_for_rag(
    *,
    question: str,
    current_user: Dict[str, Any],
    user_context: Dict[str, Any],
    domain_context: Dict[str, Any],
) -> Optional[str]:
    # 1) explicit mention in question has highest priority
    from_question = _program_type_from_text(question)
    if from_question:
        return from_question

    # 2) student/self claims from auth + profile + context
    candidates = [
        (current_user or {}).get("program_type"),
        ((current_user or {}).get("student_profile") or {}).get("program_type"),
        ((current_user or {}).get("students_progress") or {}).get("program_type"),
        (user_context or {}).get("program_type"),
    ]
    for raw in candidates:
        normalized = _normalize_program_type(raw)
        if normalized:
            return normalized

    # 3) infer from current year labels where possible
    year_candidates = [
        ((current_user or {}).get("student_profile") or {}).get("current_year"),
        (user_context or {}).get("current_year"),
    ]
    for raw in year_candidates:
        inferred = _detect_program_type_from_year_label(raw)
        if inferred:
            return inferred

    # 4) admin path: if realtime matched exactly one student, infer from that student
    matched_students = (domain_context or {}).get("matched_students_realtime") or []
    if isinstance(matched_students, list) and len(matched_students) == 1:
        student = matched_students[0] or {}
        normalized = _normalize_program_type(
            ((student.get("student_profile") or {}).get("program_type"))
            or student.get("program_type")
        )
        if normalized:
            return normalized
        inferred = _detect_program_type_from_year_label(
            (student.get("student_profile") or {}).get("current_year")
        )
        if inferred:
            return inferred

    return None


def _extract_text_from_gemini_response(data: Dict[str, Any]) -> str:
    """Extract assistant text from Gemini generateContent response."""
    candidates = data.get("candidates") or []
    if not candidates:
        return ""
    content = candidates[0].get("content") or {}
    parts = content.get("parts") or []
    text_parts: List[str] = []
    for part in parts:
        text = part.get("text")
        if isinstance(text, str) and text.strip():
            text_parts.append(text.strip())
    return "\n".join(text_parts).strip()


async def call_gemini_chat(
    question: str,
    context: str,
    history: Optional[Sequence[Dict[str, str]]] = None,
    use_rag_context: bool = True,
) -> str:
    """
    Call Gemini's generateContent endpoint with a RAG-style prompt.
    """
    if not settings.GEMINI_API_KEY:
        raise MissingAIConfigError("GEMINI_API_KEY is not configured.")

    if not settings.GEMINI_CHAT_MODEL:
        raise MissingAIConfigError("GEMINI_CHAT_MODEL is not configured.")

    chat_cache_key = _make_cache_key(
        {
            "type": "chat",
            "question": question,
            "context": context,
            "history": history or [],
            "use_rag_context": use_rag_context,
            "model": settings.GEMINI_CHAT_MODEL,
            "fallback_model": settings.GEMINI_CHAT_FALLBACK_MODEL or "",
        }
    )
    now = time.time()
    async with _CHAT_CACHE_LOCK:
        cached = _CHAT_CACHE.get(chat_cache_key)
        if cached and cached[0] > now:
            _debug_log(
                message="call_gemini_chat cache hit",
                data={"use_rag_context": use_rag_context},
                hypothesis_id="H5",
            )
            return cached[1]
        inflight = _CHAT_INFLIGHT.get(chat_cache_key)
        if inflight is None:
            loop = asyncio.get_running_loop()
            inflight = loop.create_future()
            _CHAT_INFLIGHT[chat_cache_key] = inflight
            is_owner = True
        else:
            is_owner = False

    if not is_owner:
        return await inflight

    if use_rag_context and context.strip():
        system_content_base = (
            "You are an assistant for a student enrollment and credit management system.\n"
            "Use the provided context as your primary source of truth.\n"
            "If context is relevant, prioritize it over general knowledge.\n"
            "When both 'Structured Context' and 'Retrieved Knowledge' are present:\n"
            "- Prefer Structured Context for user-specific facts (counts, completed/failed courses, GPA, status).\n"
            "- Use Retrieved Knowledge mainly for policy/background explanations.\n\n"
            f"Context:\n{context}"
        )
    else:
        system_content_base = (
            "You are an assistant for a student enrollment and credit management system.\n"
            "No knowledge-base context was retrieved for this question.\n"
            "Answer using your general knowledge and reasoning.\n"
            "If you are uncertain, say so briefly and provide the best helpful guidance."
        )

    system_messages: List[str] = []
    contents: List[Dict[str, Any]] = []

    # Convert history into Gemini content turns.
    if history:
        for msg in history:
            role = msg.get("role")
            content = msg.get("content")
            if not isinstance(content, str) or not content.strip():
                continue
            if role == "system":
                system_messages.append(content.strip())
            elif role == "assistant":
                contents.append({"role": "model", "parts": [{"text": content}]})
            elif role == "user":
                contents.append({"role": "user", "parts": [{"text": content}]})

    contents.append({"role": "user", "parts": [{"text": question}]})

    system_instruction = system_content_base
    if system_messages:
        system_instruction = (
            f"{system_content_base}\n\nAdditional system instructions:\n"
            + "\n".join(system_messages)
        )

    models_to_try: List[str] = [settings.GEMINI_CHAT_MODEL]
    fallback_model = settings.GEMINI_CHAT_FALLBACK_MODEL
    if fallback_model and fallback_model != settings.GEMINI_CHAT_MODEL:
        models_to_try.append(fallback_model)

    async with httpx.AsyncClient(timeout=60.0) as client:
        max_retries = max(0, int(settings.GEMINI_MAX_RETRIES))
        base_delay = max(0.1, float(settings.GEMINI_RETRY_BASE_SECONDS))
        max_delay = max(base_delay, float(settings.GEMINI_RETRY_MAX_SECONDS))

        try:
            for model in models_to_try:
                model_path = model if model.startswith("models/") else f"models/{model}"
                url = f"{settings.GEMINI_API_BASE.rstrip('/')}/{model_path}:generateContent"
                headers = {
                    "x-goog-api-key": settings.GEMINI_API_KEY,
                    "Content-Type": "application/json",
                }
                payload: Dict[str, Any] = {
                    "systemInstruction": {"parts": [{"text": system_instruction}]},
                    "contents": contents,
                    "generationConfig": {"temperature": 0.2},
                }

                for attempt in range(max_retries + 1):
                    try:
                        async with _GEMINI_REQUEST_SEMAPHORE:
                            await _throttle_gemini_request_rate()
                            resp = await client.post(url, headers=headers, json=payload)
                        if resp.status_code == 429:
                            retry_after_header = resp.headers.get("Retry-After")
                            retry_after: Optional[float] = None
                            if retry_after_header:
                                try:
                                    retry_after = float(retry_after_header)
                                except ValueError:
                                    retry_after = None
                            backoff = min(max_delay, base_delay * (2**attempt))
                            wait_seconds = retry_after if retry_after and retry_after > 0 else backoff

                            if attempt < max_retries:
                                await asyncio.sleep(wait_seconds)
                                continue

                            _debug_log(
                                message="call_gemini_chat rate limited after retries",
                                data={
                                    "model": model,
                                    "attempts": max_retries + 1,
                                    "retry_after_header": retry_after_header,
                                    "wait_seconds": wait_seconds,
                                },
                                hypothesis_id="H5",
                            )

                            raise RateLimitedAIError(
                                f"AI provider is rate-limited right now. Please retry in about {int(math.ceil(wait_seconds))} seconds."
                            )
                        if 500 <= resp.status_code < 600 and attempt < max_retries:
                            backoff = min(max_delay, base_delay * (2**attempt))
                            await asyncio.sleep(backoff)
                            continue
                        resp.raise_for_status()
                        data = resp.json()
                        content = _extract_text_from_gemini_response(data)
                        if content:
                            async with _CHAT_CACHE_LOCK:
                                _CHAT_CACHE[chat_cache_key] = (time.time() + _CHAT_CACHE_TTL_SECONDS, content)
                                _prune_cache_if_needed(_CHAT_CACHE)
                                inflight_result = _CHAT_INFLIGHT.pop(chat_cache_key, None)
                                if inflight_result and not inflight_result.done():
                                    inflight_result.set_result(content)
                            return content
                        if model != models_to_try[-1]:
                            break
                        raise ChatServiceError("Gemini chat API returned an empty response.")
                    except (httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError) as exc:
                        if attempt >= max_retries:
                            if model != models_to_try[-1]:
                                break
                            raise ChatServiceError(f"Error calling Gemini chat API: {exc}") from exc
                        backoff = min(max_delay, base_delay * (2**attempt))
                        await asyncio.sleep(backoff)
                    except httpx.HTTPStatusError as exc:
                        # Try fallback model for non-rate-limit provider failures.
                        if model != models_to_try[-1] and exc.response.status_code in {404, 500, 502, 503, 504}:
                            break
                        if exc.response.status_code == 429:
                            raise RateLimitedAIError("AI provider is rate-limited right now. Please retry shortly.") from exc
                        raise ChatServiceError(f"Error calling Gemini chat API: {exc}") from exc
                    except httpx.HTTPError as exc:
                        raise ChatServiceError(f"Error calling Gemini chat API: {exc}") from exc

            raise RateLimitedAIError("AI provider is rate-limited right now. Please retry shortly.")
        except Exception as exc:
            async with _CHAT_CACHE_LOCK:
                inflight_error = _CHAT_INFLIGHT.pop(chat_cache_key, None)
                if inflight_error and not inflight_error.done():
                    inflight_error.set_exception(exc)
            raise


async def chat_with_rag(
    question: str,
    history: Optional[Sequence[Dict[str, str]]] = None,
) -> Tuple[str, List[Dict[str, Any]]]:
    """
    High-level entry point for the chatbot:

    1. Embed the user's question.
    2. Run vector search on KnowledgeBase.
    3. Build a context string from top results.
    4. Call Gemini chat completion with that context.

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
    embeddings = await embed_texts([question], task_type="RETRIEVAL_QUERY")
    query_embedding = embeddings[0]

    # 2. Vector search in MongoDB Atlas
    results = await vector_search_knowledge(query_embedding=query_embedding, limit=5, num_candidates=100)

    # 3. Build context and source metadata
    context, sources = _build_context_from_results(results)

    # 4. Call Gemini chat:
    #    - with KB-grounded behavior when results exist
    #    - fallback to general LLM response when no KB hits exist
    answer = await call_gemini_chat(
        question=question,
        context=context,
        history=history,
        use_rag_context=bool(sources),
    )

    return answer, sources


def _classify_intent(question: str, mode: str = "auto", course_id: Optional[str] = None) -> str:
    """Lightweight deterministic intent classifier."""
    if mode and mode != "auto":
        return mode
    if course_id and str(course_id).strip():
        return "course_advisor"

    q = question.lower()
    course_terms = ["course", "courses", "subject", "á€žá€„á€ºá€á€”á€ºá€¸", "á€˜á€¬á€žá€¬"]
    count_terms = ["how many", "number of", "count", "total", "amount", "á€˜á€šá€ºá€”á€¾", "á€¡á€›á€±á€¡á€á€½á€€á€º", "á€…á€¯á€…á€¯á€•á€±á€«á€„á€ºá€¸"]
    announcement_terms = ["announcement", "notice", "event", "urgent", "á€€á€¼á€±á€Šá€¬", "á€¡á€žá€­á€•á€±á€¸", "á€¡á€›á€±á€¸á€•á€±á€«á€º"]
    major_terms = ["major", "requirement", "department", "á€™á€±á€‚á€»á€¬", "á€Œá€¬á€”", "á€œá€­á€¯á€¡á€•á€ºá€á€»á€€á€º"]
    history_terms = [
        "academic history",
        "history",
        "completed",
        "failed",
        "passed",
        "retake",
        "á€•á€¼á€®á€¸á€†á€¯á€¶á€¸",
        "á€€á€»á€›á€¾á€¯á€¶á€¸",
        "á€¡á€±á€¬á€„á€º",
        "á€™á€¡á€±á€¬á€„á€º",
        "á€™á€¾á€á€ºá€á€™á€ºá€¸",
    ]
    course_selection_terms = ["credit", "enroll", "course selection", "prerequisite", "available", "offer", "offered", "list", "show", "take", "á€…á€¬á€›á€„á€ºá€¸", "á€•á€¼á€ž"]

    course_advisor_terms = [
        "this course",
        "that course",
        "particular course",
        "enrolled",
        "passed",
        "failed",
        "average grade",
        "fit",
        "suited",
        "suitable",
    ]

    if any(k in q for k in course_terms) and any(k in q for k in count_terms):
        return "course_stats"
    if any(k in q for k in course_advisor_terms):
        return "course_advisor"
    if any(k in q for k in announcement_terms):
        return "announcements"
    if any(k in q for k in major_terms):
        return "major_requirements"
    if any(k in q for k in history_terms):
        return "academic_progress"
    if any(k in q for k in ["credit", "retake", "enroll", "course selection", "prerequisite", "á€…á€¬á€›á€„á€ºá€¸á€žá€½á€„á€ºá€¸"]):
        return "course_selection"
    if any(k in q for k in course_terms) and any(k in q for k in course_selection_terms):
        return "course_selection"
    if any(k in q for k in ["gpa", "cgpa", "progress", "academic status", "completed", "á€á€­á€¯á€¸á€á€€á€ºá€™á€¾á€¯"]):
        return "academic_progress"
    return "policy_general"


def _should_use_rag(intent: str) -> bool:
    if intent in {"academic_progress", "course_advisor"}:
        # Personal progress questions are better answered from live structured DB context.
        return False
    return intent in {
        "course_selection",
        "major_requirements",
        "announcements",
        "policy_general",
        # For direct DB count/stat questions, prefer structured context only.
        # This avoids irrelevant KB snippets overriding database facts.
        # Example: "How many courses are there?"
        # Intent = course_stats -> no RAG.
    }


async def chat_with_base_model(
    question: str,
    current_user: Dict[str, Any],
    history: Optional[Sequence[Dict[str, str]]] = None,
    mode: str = "auto",
    course_id: Optional[str] = None,
    include_admin_student_data: bool = False,
) -> Tuple[str, List[Dict[str, Any]]]:
    """
    Reusable base AI orchestration:
      1) classify intent
      2) build real-time structured context
      3) optionally run vector retrieval
      4) compose hybrid prompt context
      5) generate final answer
    """
    intent = _classify_intent(question, mode=mode, course_id=course_id)

    user_context = await build_user_context(current_user=current_user, intent=intent)
    domain_context = await build_domain_context(
        intent=intent,
        current_user=current_user,
        course_id=course_id,
        include_admin_student_data=include_admin_student_data,
    )
    realtime_context = await build_realtime_context(
        question=question,
        current_user=current_user,
        intent=intent,
        course_id=course_id,
        existing_context=domain_context,
        include_admin_student_data=include_admin_student_data,
    )
    if realtime_context:
        domain_context = {**domain_context, **realtime_context}
    structured_context_obj = {
        "intent": intent,
        "user_context": user_context,
        "domain_context": domain_context,
    }
    structured_context_text = serialize_context_for_prompt(structured_context_obj)

    sources: List[Dict[str, Any]] = []
    rag_context = ""
    if _should_use_rag(intent) and int(settings.AI_RAG_K) > 0:
        embeddings = await embed_texts([question], task_type="RETRIEVAL_QUERY")
        query_embedding = embeddings[0]
        metadata_filter: Dict[str, Any] = {}
        if intent == "announcements":
            metadata_filter["metadata.type"] = "announcements"
        program_type = _resolve_program_type_for_rag(
            question=question,
            current_user=current_user,
            user_context=user_context,
            domain_context=domain_context,
        )
        if program_type:
            metadata_filter["metadata.program_type"] = program_type
        rag_results = await vector_search_knowledge(
            query_embedding=query_embedding,
            limit=settings.AI_RAG_K,
            num_candidates=settings.AI_RAG_NUM_CANDIDATES,
            score_threshold=settings.AI_RAG_SCORE_THRESHOLD,
            metadata_filter=metadata_filter or None,
        )
        rag_context, sources = _build_context_from_results(rag_results)

    context_sections: List[str] = []
    if structured_context_text:
        context_sections.append(f"Structured Context:\n{structured_context_text}")
    if rag_context:
        context_sections.append(f"Retrieved Knowledge:\n{rag_context}")
    combined_context = "\n\n====\n\n".join(context_sections)

    response_mode = "general"
    if structured_context_text and rag_context:
        response_mode = "hybrid"
    elif structured_context_text:
        response_mode = "structured_only"
    elif rag_context:
        response_mode = "rag_only"

    _debug_log(
        message="chat_with_base_model orchestration",
        data={
            "intent": intent,
            "structured_context_chars": len(structured_context_text),
            "rag_context_chars": len(rag_context),
            "retrieved_sources": len(sources),
            "response_mode": response_mode,
            "realtime_context_used": bool(realtime_context),
            "realtime_context_keys": list(realtime_context.keys())[:20] if realtime_context else [],
            "rag_program_filter": _resolve_program_type_for_rag(
                question=question,
                current_user=current_user,
                user_context=user_context,
                domain_context=domain_context,
            ),
        },
        hypothesis_id="H5",
    )

    answer = await call_gemini_chat(
        question=question,
        context=combined_context,
        history=history,
        use_rag_context=bool(combined_context.strip()),
    )

    return answer, sources


async def chat_with_student_model(
    question: str,
    current_user: Dict[str, Any],
    history: Optional[Sequence[Dict[str, str]]] = None,
    mode: str = "auto",
    course_id: Optional[str] = None,
) -> Tuple[str, List[Dict[str, Any]]]:
    return await chat_with_base_model(
        question=question,
        current_user=current_user,
        history=history,
        mode=mode,
        course_id=course_id,
        include_admin_student_data=False,
    )


async def chat_with_admin_model(
    question: str,
    current_user: Dict[str, Any],
    history: Optional[Sequence[Dict[str, str]]] = None,
    mode: str = "auto",
    course_id: Optional[str] = None,
) -> Tuple[str, List[Dict[str, Any]]]:
    return await chat_with_base_model(
        question=question,
        current_user=current_user,
        history=history,
        mode=mode,
        course_id=course_id,
        include_admin_student_data=True,
    )


