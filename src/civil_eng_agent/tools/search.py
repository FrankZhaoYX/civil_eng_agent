"""search_guidelines tool: hybrid semantic + BM25 search over guideline prose."""
from __future__ import annotations

import json

from civil_eng_agent.citations import Citation, CitedChunk
from civil_eng_agent.config import Config
from civil_eng_agent.store.repository import Repository


def search_guidelines(
    query: str,
    road_type: str | None = None,
    topic: str | None = None,
    category: str | None = None,
    subcategory: str | None = None,
    limit: int = 8,
    cfg: Config | None = None,
    repo: Repository | None = None,
) -> list[CitedChunk]:
    """Hybrid semantic + BM25 search over guideline prose.

    Returns up to `limit` chunks with citations, ranked by relevance.
    Filters by road_type tag, topic tag, category, or subcategory when supplied.
    """
    if cfg is None:
        cfg = Config.load()
    if repo is None:
        repo = Repository(cfg.db_path)

    doc_ids = _filter_doc_ids(repo, category, subcategory)

    # Collect candidates from both vector and FTS paths, then merge
    seen: dict[int, CitedChunk] = {}

    if repo.has_vec() and not cfg.air_gapped:
        try:
            from civil_eng_agent.ingestion.chunk_embed import embed_texts
            query_vec = embed_texts([query], cfg)[0]
            vec_rows = repo.vector_search(query_vec, limit=limit * 2)
            for row in vec_rows:
                _add_row(row, seen, doc_ids, road_type, topic, score_key="distance", invert=True)
        except Exception:
            pass

    fts_rows = repo.fts_search(_fts_query(query), limit=limit * 2)
    for row in fts_rows:
        # BM25 in FTS5 is negative; negate so higher = better, consistent with vec scores
        _add_row(row, seen, doc_ids, road_type, topic, score_key="score", invert=False)

    # Sort by score descending, take top `limit`
    results = sorted(seen.values(), key=lambda c: c.score, reverse=True)[:limit]

    # Attach document metadata
    doc_cache: dict[str, dict] = {}
    for chunk in results:
        doc_id = chunk.citation.doc_id
        if doc_id not in doc_cache:
            rows = repo._conn.execute(
                "SELECT * FROM documents WHERE doc_id = ?", (doc_id,)
            ).fetchall()
            if rows:
                doc_cache[doc_id] = dict(rows[0])
        meta = doc_cache.get(doc_id, {})
        chunk.citation.category = meta.get("category", chunk.citation.category)
        chunk.citation.subcategory = meta.get("subcategory", chunk.citation.subcategory)
        chunk.citation.doc_title = meta.get("title", doc_id)
        chunk.citation.version_date = meta.get("version_date")

    return results


def _fts_query(query: str) -> str:
    # Join terms with OR so any matching chunk is returned;
    # BM25 naturally ranks chunks that match more terms higher.
    import re
    terms = re.findall(r'\w+', query)
    if not terms:
        return query
    return " OR ".join(terms)


def _filter_doc_ids(
    repo: Repository,
    category: str | None,
    subcategory: str | None,
) -> set[str] | None:
    if not category and not subcategory:
        return None
    docs = repo.list_documents(category=category, subcategory=subcategory)
    return {d["doc_id"] for d in docs}


def _add_row(
    row,
    seen: dict[int, CitedChunk],
    doc_ids: set[str] | None,
    road_type: str | None,
    topic: str | None,
    score_key: str,
    invert: bool = False,
) -> None:
    chunk_id = row["chunk_id"]
    doc_id = row["doc_id"]

    if doc_ids is not None and doc_id not in doc_ids:
        return

    if road_type:
        rt_list = json.loads(row["road_types"] or "[]")
        if road_type.lower() not in [r.lower() for r in rt_list]:
            return

    if topic:
        topic_list = json.loads(row["topics"] or "[]")
        if topic.lower() not in [t.lower() for t in topic_list]:
            return

    raw_score = row[score_key]
    score = -raw_score if invert else raw_score  # BM25 is negative in FTS5

    if chunk_id in seen:
        if score > seen[chunk_id].score:
            seen[chunk_id].score = score
    else:
        seen[chunk_id] = CitedChunk(
            chunk_id=chunk_id,
            chunk_text=row["chunk_text"],
            score=score,
            citation=Citation(
                category="",
                subcategory="",
                doc_id=doc_id,
                doc_title=doc_id,
                section=row["section"],
                page=row["page"],
            ),
        )
