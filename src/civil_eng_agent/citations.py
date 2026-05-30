"""Citation models and validation."""
from __future__ import annotations

from pydantic import BaseModel


class Citation(BaseModel):
    category: str
    subcategory: str
    doc_id: str
    doc_title: str
    section: str | None = None
    page: int | None = None
    version_date: str | None = None


class CitedChunk(BaseModel):
    chunk_id: int
    chunk_text: str
    score: float
    citation: Citation
