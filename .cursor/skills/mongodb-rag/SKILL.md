---
name: mongodb-rag
description: Design, debug, and optimize Retrieval-Augmented Generation (RAG) systems using MongoDB Atlas Vector Search with Python (including FastAPI backends) and LangChain. Use when the user asks about MongoDB-based RAG, Atlas Vector Search, embeddings, or LangChain retrieval pipelines.
---

# MongoDB Atlas RAG

## Purpose

Help the agent design, debug, and optimize RAG systems built with:
- MongoDB Atlas Vector Search
- Python (pymongo or official Python driver, including FastAPI-based services)
- LangChain or similar orchestration frameworks
- Custom or hosted embedding models

Focus on:
- Embedding correctness and dimensionality
- Vector index configuration
- Query and retrieval architecture
- Practical debugging and optimization levers

## Instructions

### 1. Embedding Pipeline

When assisting with embeddings:
- Ensure that text is embedded before storage.
- Verify that the embedding vector length matches the index `numDimensions`.
- Recommend batching for large insert workloads.
- If the similarity metric requires it (for example, cosine), suggest normalizing vectors consistently.

### 2. MongoDB Document Structure

Recommend a document shape similar to:

```json
{
  "text": "Original content",
  "embedding": [0.01, 0.23, ...],
  "metadata": {
    "source": "...",
    "hasCode": false
  }
}
```

Guidelines:
- `embedding` must be a numeric array (float values).
- Vector dimension must match the embedding model and index configuration.
- Metadata fields that are used for filtering should be simple and indexable (for example, booleans, enums, or short strings).

### 3. Atlas Vector Index Configuration

When helping configure Atlas Vector Search, ensure an index definition similar to:

```json
{
  "fields": [
    {
      "type": "vector",
      "path": "embedding",
      "numDimensions": 1536,
      "similarity": "cosine"
    }
  ]
}
```

Validation checklist:
- `path` matches the document field that stores embeddings.
- `numDimensions` matches the chosen embedding model.
- `similarity` metric (for example, cosine, dotProduct, euclidean) is appropriate for the embedding model.

### 4. Query and Retrieval Architecture

When designing the query pipeline, follow this flow:
1. Convert the user question into an embedding.
2. Use `$vectorSearch` in an aggregation pipeline.
3. Tune retrieval using:
   - `numCandidates`
   - `limit` (number of final results)
   - Optional `score_threshold` or equivalent filtering.
4. Apply metadata filters where useful (for example, `hasCode == false`).

Example pattern:

```python
pipeline = [
  {
    "$vectorSearch": {
      "index": "vector_index",
      "path": "embedding",
      "queryVector": query_embedding,
      "numCandidates": 100,
      "limit": 5
    }
  }
]

results = collection.aggregate(pipeline)
```

Advise the user to experiment with `numCandidates`, `limit`, and any score thresholds when tuning quality.

### 5. LangChain Integration Pattern

When integrating with LangChain-style retrievers:
- Use a vector store that wraps the MongoDB Atlas Vector Search index.
- Configure the retriever with clear search parameters.

Example configuration:

```python
retriever = vector_store.as_retriever(
    search_type="similarity",
    search_kwargs={
        "k": 5,
        "score_threshold": 0.4,
        "pre_filter": {"hasCode": {"$eq": False}}
    }
)
```

Example context formatting runnable:

```python
from langchain.schema.runnable import RunnablePassthrough

retrieve = {
    "context": retriever | (lambda docs: "\n\n".join([d.page_content for d in docs])),
    "question": RunnablePassthrough()
}
```

Guidelines:
- Always convert retrieved documents to plain text before sending to the model.
- Keep the prompt template explicit, for example expecting `{context}` and `{question}`.

### 6. Optimization Guidelines

When the user wants to tune quality, provide these rules.

For higher relevance:
- Raise any score or similarity thresholds.
- Lower `k` to focus on top matches.
- Improve chunking (semantic, by headings, or code-aware).

For higher recall:
- Increase `numCandidates`.
- Lower score thresholds.
- Consider a stronger or domain-specific embedding model.

### 7. Common Failure Modes

Help the user diagnose issues using these patterns:
- No results returned: score threshold too high, overly strict filters, or index not built.
- Irrelevant results: score threshold too low, poor chunking, or misaligned embedding model.
- Runtime errors: embedding dimension mismatches index `numDimensions`, wrong `path`, or missing index.
- Poor answers or hallucinations: weak retrieval (too few or irrelevant documents) or missing context formatting.

### 8. End-to-End RAG Flow

Always think in terms of the full pipeline:

Text → Embedding → Store → Index → Query → Embed Question → Vector Search → Retrieved Context → Prompt → LLM

Reminders:
- Do not store only raw text without embeddings if vector search is required.
- Do not mismatch embedding model dimension and index configuration.
- Do not send raw driver or Document objects directly to the LLM; convert to text summaries or snippets.

### 9. Scaling and Observability

For production-grade systems, recommend:
- A dedicated embedding service or background worker for batch ingestion.
- Caching query embeddings where appropriate.
- Logging similarity scores alongside prompts and answers to analyze retrieval quality.
- Periodic evaluation of retrieval (for example, relevance labeling or offline tests).
- Considering hybrid search (for example, combining keyword or BM25 with vector search) for certain domains.

## Examples

- When a user asks: "Why am I getting a dimension mismatch error with Atlas Vector Search?" use this skill to inspect their embedding model, index `numDimensions`, and document structure.
- When a user asks: "How do I connect LangChain to MongoDB Atlas for RAG?" use the LangChain retriever and pipeline patterns above.
- When a user reports irrelevant answers, walk through optimization levers: chunking strategy, `numCandidates`, thresholds, and metadata filters.

