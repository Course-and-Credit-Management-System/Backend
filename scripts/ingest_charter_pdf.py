"""
Ingest documents into the RAG KnowledgeBase with quality-oriented chunking.

Supported inputs:
  - Single file: .pdf, .docx, .txt, .md
  - Directory: recursively ingests supported files

Usage (from Backend/ directory):

    python -m scripts.ingest_charter_pdf
    python -m scripts.ingest_charter_pdf "C:\\path\\to\\file.docx"
    python -m scripts.ingest_charter_pdf "C:\\path\\to\\docs_folder" --chunk-size 1000 --overlap 150
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import sys
import zipfile
from argparse import ArgumentParser
from pathlib import Path
from typing import Iterable, List
from xml.etree import ElementTree as ET

from pypdf import PdfReader

from app.core.config import settings
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


def extract_text_from_docx(docx_path: Path) -> str:
    """Extract plain text from .docx using stdlib zip/xml."""
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    with zipfile.ZipFile(docx_path) as zf:
        xml = zf.read("word/document.xml")
    root = ET.fromstring(xml)
    paragraphs: List[str] = []
    for p in root.findall(".//w:p", ns):
        parts = [t.text or "" for t in p.findall(".//w:t", ns)]
        line = "".join(parts).strip()
        if line:
            paragraphs.append(line)
    return "\n\n".join(paragraphs)


def extract_text_from_plain(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def read_document_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return extract_text_from_pdf(path)
    if suffix == ".docx":
        return extract_text_from_docx(path)
    if suffix in {".txt", ".md", ".docs"}:
        return extract_text_from_plain(path)
    raise ValueError(f"Unsupported file type: {path.suffix}")


def normalize_text(text: str) -> str:
    lines = [ln.rstrip() for ln in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    cleaned: List[str] = []
    blank = 0
    for ln in lines:
        stripped = re.sub(r"[ \t]+", " ", ln).strip()
        if not stripped:
            blank += 1
            if blank <= 1:
                cleaned.append("")
        else:
            blank = 0
            cleaned.append(stripped)
    return "\n".join(cleaned).strip()


def _normalize_program_type(value: str) -> str | None:
    normalized = (value or "").strip().lower().replace(" ", "").replace("-", "")
    if not normalized:
        return None
    if normalized in {"4year", "4years", "fouryear", "year4"}:
        return "4year"
    if normalized in {"5year", "5years", "fiveyear", "year5"}:
        return "5year"
    if "4year" in normalized or "fouryear" in normalized:
        return "4year"
    if "5year" in normalized or "fiveyear" in normalized:
        return "5year"
    return None


def infer_program_type(file_path: Path, text: str) -> str | None:
    """Infer a coarse program bucket so retrieval can filter between similar files."""
    filename = file_path.name.lower()
    from_filename = None
    if re.search(r"\b4\s*[-_ ]?year\b", filename) or "four year" in filename:
        from_filename = "4year"
    if re.search(r"\b5\s*[-_ ]?year\b", filename) or "five year" in filename:
        from_filename = "5year"
    if from_filename:
        return from_filename

    sample = (text or "")[:4000].lower()
    if re.search(r"\b4\s*[- ]?year\b", sample) or "four year" in sample:
        return "4year"
    if re.search(r"\b5\s*[- ]?year\b", sample) or "five year" in sample:
        return "5year"
    return None


def build_chunk_anchor(source: str, program_type: str | None, chunk_index: int, chunk_total: int) -> str:
    program_label = program_type or "unspecified"
    return f"[Source: {source} | Program: {program_label} | Chunk: {chunk_index + 1}/{chunk_total}]"


def with_anchor(anchor: str, chunk: str) -> str:
    return f"{anchor}\n{chunk}".strip()


def _split_long_paragraph(paragraph: str, max_chars: int) -> List[str]:
    sentences = re.split(r"(?<=[.!?])\s+", paragraph)
    sentences = [s.strip() for s in sentences if s.strip()]
    if not sentences:
        return []
    parts: List[str] = []
    cur = ""
    for s in sentences:
        if len(s) > max_chars:
            words = s.split()
            buf = ""
            for w in words:
                candidate = f"{buf} {w}".strip()
                if len(candidate) <= max_chars:
                    buf = candidate
                else:
                    if buf:
                        parts.append(buf)
                    buf = w
            if buf:
                if cur:
                    parts.append(cur)
                    cur = ""
                parts.append(buf)
            continue

        candidate = f"{cur} {s}".strip()
        if not cur or len(candidate) <= max_chars:
            cur = candidate
        else:
            parts.append(cur)
            cur = s
    if cur:
        parts.append(cur)
    return parts


def _tail_for_overlap(text: str, overlap_chars: int) -> str:
    if overlap_chars <= 0 or not text:
        return ""
    tail = text[-overlap_chars:]
    if " " in tail:
        tail = tail[tail.find(" ") + 1 :]
    return tail.strip()


def chunk_text_semantic(text: str, max_chars: int = 1000, overlap_chars: int = 150) -> List[str]:
    """Chunk by paragraphs/sentences with overlap for better retrieval continuity."""
    text = normalize_text(text)
    if not text:
        return []

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    units: List[str] = []
    for p in paragraphs:
        if len(p) <= max_chars:
            units.append(p)
        else:
            units.extend(_split_long_paragraph(p, max_chars=max_chars))

    base_chunks: List[str] = []
    cur = ""
    for u in units:
        candidate = f"{cur}\n\n{u}".strip() if cur else u
        if len(candidate) <= max_chars:
            cur = candidate
        else:
            if cur:
                base_chunks.append(cur.strip())
            cur = u
    if cur:
        base_chunks.append(cur.strip())

    if overlap_chars <= 0 or len(base_chunks) <= 1:
        return base_chunks

    chunks = [base_chunks[0]]
    for i in range(1, len(base_chunks)):
        overlap = _tail_for_overlap(base_chunks[i - 1], overlap_chars)
        merged = f"{overlap}\n\n{base_chunks[i]}".strip() if overlap else base_chunks[i]
        chunks.append(merged)
    return chunks


def resolve_input_files(input_path: Path) -> List[Path]:
    supported = {".pdf", ".docx", ".txt", ".md", ".docs"}
    if input_path.is_file():
        return [input_path]
    if input_path.is_dir():
        return sorted([p for p in input_path.rglob("*") if p.is_file() and p.suffix.lower() in supported])
    raise FileNotFoundError(f"Path not found: {input_path}")


def parse_args(argv: Iterable[str]) -> tuple[Path, int, int]:
    parser = ArgumentParser(description="Ingest documents into KnowledgeBase for RAG.")
    parser.add_argument("path", nargs="?", default=r"C:\Users\USER\Downloads")
    parser.add_argument("--chunk-size", type=int, default=1000)
    parser.add_argument("--overlap", type=int, default=150)
    args = parser.parse_args(list(argv))
    return Path(args.path), max(300, args.chunk_size), max(0, args.overlap)


async def get_collection_with_retry(retries: int = 3, delay_seconds: float = 2.0):
    """Get knowledge collection with simple retry for transient Atlas primary elections."""
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            db = await get_database()
            await db.command("ping")
            return db[settings.KNOWLEDGE_BASE_COLLECTION]
        except Exception as exc:  # pragma: no cover - operational resilience
            last_error = exc
            if attempt < retries:
                print(f"[ingest] Mongo connection attempt {attempt}/{retries} failed, retrying...")
                await asyncio.sleep(delay_seconds)
            else:
                break
    raise RuntimeError(f"Unable to connect to MongoDB after {retries} attempts: {last_error}")


async def main(input_path: Path, chunk_size: int, overlap: int) -> None:
    files = resolve_input_files(input_path)
    if not files:
        raise RuntimeError("No supported files found (.pdf, .docx, .txt, .md, .docs).")

    collection = await get_collection_with_retry()
    print(f"[ingest] Found {len(files)} file(s).")
    all_docs: List[dict] = []

    for file_path in files:
        print(f"[ingest] Reading: {file_path}")
        full_text = read_document_text(file_path)
        full_text = normalize_text(full_text)
        if not full_text:
            print(f"[ingest] Skipping empty text: {file_path.name}")
            continue

        chunks = chunk_text_semantic(full_text, max_chars=chunk_size, overlap_chars=overlap)
        if not chunks:
            print(f"[ingest] No chunks generated: {file_path.name}")
            continue

        program_type = _normalize_program_type(infer_program_type(file_path, full_text) or "")
        anchored_chunks: List[str] = []
        for idx, chunk in enumerate(chunks):
            anchor = build_chunk_anchor(file_path.name, program_type, idx, len(chunks))
            anchored_chunks.append(with_anchor(anchor, chunk))

        print(f"[ingest] {file_path.name}: {len(chunks)} chunks")
        embeddings = await embed_texts(anchored_chunks, task_type="RETRIEVAL_DOCUMENT")
        if len(embeddings) != len(chunks):
            raise RuntimeError(f"Embeddings mismatch for {file_path.name}: {len(embeddings)} vs {len(chunks)}")

        # Replace previously ingested chunks for this source to avoid duplicate retrieval noise.
        await collection.delete_many(
            {
                "metadata.type": "docs",
                "$or": [
                    {"metadata.path": str(file_path)},
                    {"metadata.source": file_path.name},
                ],
            }
        )

        for idx, (chunk, emb, anchored_chunk) in enumerate(zip(chunks, embeddings, anchored_chunks)):
            chunk_hash = hashlib.sha256(chunk.encode("utf-8")).hexdigest()
            all_docs.append(
                {
                    "text": anchored_chunk,
                    "embedding": emb,
                    "metadata": {
                        "source": file_path.name,
                        "path": str(file_path),
                        "type": "docs",
                        "format": file_path.suffix.lower().lstrip("."),
                        "program_type": program_type,
                        "hasCode": "```" in chunk or re.search(r"\b(class|def|function|SELECT|INSERT)\b", chunk) is not None,
                        "chunk_index": idx,
                        "chunk_total": len(chunks),
                        "chunk_chars": len(chunk),
                        "chunk_hash": chunk_hash,
                        "embedding_provider": "gemini",
                        "embedding_model": settings.GEMINI_EMBEDDING_MODEL,
                        "embedding_dimensions": settings.EMBEDDING_DIMENSIONS,
                    },
                }
            )

    if not all_docs:
        print("[ingest] Nothing to insert.")
        return

    print(f"[ingest] Inserting {len(all_docs)} chunks into {settings.KNOWLEDGE_BASE_COLLECTION}...")
    await collection.insert_many(all_docs)
    print("[ingest] Done.")


if __name__ == "__main__":
    input_path, chunk_size, overlap = parse_args(sys.argv[1:])
    asyncio.run(main(input_path, chunk_size, overlap))
