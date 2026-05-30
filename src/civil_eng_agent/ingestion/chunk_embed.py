"""Chunking and embedding: produce embeddings for a list of text chunks."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from civil_eng_agent.config import Config


def embed_texts(texts: list[str], cfg: "Config") -> list[list[float]]:
    """Return embedding vectors for each text, using Voyage-3 or local fallback."""
    if not texts:
        return []
    if cfg.embed.provider == "voyage":
        return _voyage_embed(texts, cfg)
    return _local_embed(texts, cfg)


def _voyage_embed(texts: list[str], cfg: "Config") -> list[list[float]]:
    import voyageai  # type: ignore

    client = voyageai.Client(api_key=cfg.voyage_api_key)
    batch_size = 128
    results: list[list[float]] = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        resp = client.embed(batch, model=cfg.embed.voyage_model, input_type="document")
        results.extend(resp.embeddings)
    return results


def _local_embed(texts: list[str], cfg: "Config") -> list[list[float]]:
    from sentence_transformers import SentenceTransformer  # type: ignore

    model = SentenceTransformer(cfg.embed.local_model)
    vecs = model.encode(texts, show_progress_bar=False)
    return [v.tolist() for v in vecs]
