"""DOCX parsing for specs and bid forms."""
from __future__ import annotations

import re
from pathlib import Path

from docx import Document

from .parse_pdf import chunk_text, normalize, split_paragraphs, tag_road_types, tag_topics


def parse_docx_chunks(
    docx_path: Path,
    doc_id: str,
    chunk_size: int = 1200,
    overlap: int = 200,
    min_chars: int = 80,
) -> list[dict]:
    try:
        doc = Document(docx_path)
    except Exception as exc:
        print(f"  Warning: DOCX extraction error in {docx_path.name}: {exc}")
        return []

    records: list[dict] = []
    current_section = ""
    para_idx = 0

    for para in doc.paragraphs:
        text = normalize(para.text)
        if not text:
            continue

        # Detect headings as section markers
        if para.style.name.startswith("Heading"):
            current_section = text
            continue

        if len(text) < min_chars:
            continue

        parts = [text] if len(text) <= chunk_size else chunk_text(text, chunk_size, overlap)
        for chunk in parts:
            if len(chunk) < min_chars:
                continue
            para_idx += 1
            records.append({
                "doc_id": doc_id,
                "section": current_section,
                "page": None,
                "road_types": tag_road_types(chunk),
                "topics": tag_topics(chunk),
                "chunk_text": chunk,
            })

    return records
