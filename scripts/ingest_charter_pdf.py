"""
One-off script to ingest the UCS Sittway Charter PDF into the RAG KnowledgeBase.

Usage (from Backend/ directory):

    pip install -r requirements.txt
    # Ensure MONGODB_URL, MONGODB_DB_NAME, MISTRAL_API_KEY, EMBEDDING_MODEL are set in .env

    python -m scripts.ingest_charter_pdf
    # or provide a custom path:
    python -m scripts.ingest_charter_pdf "C:\\Users\\USER\\Downloads\\4-CS-7313-Object Oriented Database.pdf"

This will:
  1. Read the PDF.
  2. Split it into reasonably sized text chunks.
  3. Call Mistral embeddings to generate vectors.
  4. Insert documents into the `KnowledgeBase` collection for Atlas Vector Search.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import List

from pypdf import PdfReader

from app.core.database import get_database
from app.services.ai_chat_service import embed_texts


def extract_text_from_pdf(pdf_path: Path) -> str:
    """Extract all text from a PDF file."""
    reader = PdfReader(str(pdf_path))
    texts: List[str] = []
    for page in reader.pages:
        page_text = page.extract_text() or ""
        if page_text:
            texts.append(page_text)
    return "\n\n".join(texts)


def chunk_text(text: str, max_chars: int = 1500) -> List[str]:
    """
    Naive text chunker based on character count.

    For more advanced behavior you can later switch to sentence or paragraph-based
    chunking, but this is sufficient to get started.
    """
    text = text.strip()
    if not text:
        return []

    chunks: List[str] = []
    start = 0
    length = len(text)

    while start < length:
        end = min(start + max_chars, length)

        # Try to break on a sentence boundary or whitespace if possible.
        split_at = text.rfind(". ", start, end)
        if split_at == -1:
            split_at = text.rfind("\n", start, end)
        if split_at == -1:
            split_at = text.rfind(" ", start, end)

        if split_at == -1 or split_at <= start + max_chars * 0.5:
            split_at = end
        else:
            split_at += 1  # include the period or space

        chunk = text[start:split_at].strip()
        if chunk:
            chunks.append(chunk)
        start = split_at

    return chunks


async def main(pdf_path: Path) -> None:
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    print(f"[ingest] Reading PDF from: {pdf_path}")
    full_text = extract_text_from_pdf(pdf_path)
    if not full_text.strip():
        raise RuntimeError("No text extracted from PDF; check the file contents.")

    print("[ingest] Chunking text...")
    chunks = chunk_text(full_text, max_chars=1500)
    print(f"[ingest] Created {len(chunks)} chunks.")

    print("[ingest] Generating embeddings via Mistral...")
    embeddings = await embed_texts(chunks)
    if len(embeddings) != len(chunks):
        raise RuntimeError(
            f"Embeddings length mismatch: {len(embeddings)} vs chunks {len(chunks)}"
        )

    db = await get_database()
    collection = db["KnowledgeBase"]

    docs = []
    for chunk, emb in zip(chunks, embeddings):
        docs.append(
            {
                "text": chunk,
                "embedding": emb,
                "metadata": {
                    "source": pdf_path.name,
                    "path": str(pdf_path),
                    "type": "docs",
                    "hasCode": False,
                },
            }
        )

    if not docs:
        print("[ingest] No documents to insert.")
        return

    print(f"[ingest] Inserting {len(docs)} documents into KnowledgeBase...")
    await collection.insert_many(docs)
    print("[ingest] Done. KnowledgeBase is now populated for this PDF.")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        pdf = Path(sys.argv[1])
    else:
        pdf = Path(r"C:\Users\USER\Downloads\UCS_Sittway_Charter_Fifth_Draft.pdf")
    asyncio.run(main(pdf))

