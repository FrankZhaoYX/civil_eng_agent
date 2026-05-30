"""list_applicable_documents tool: which docs should be consulted for a given scope."""
from __future__ import annotations

from pydantic import BaseModel

from civil_eng_agent.config import Config
from civil_eng_agent.store.repository import Repository


class DocumentReference(BaseModel):
    doc_id: str
    title: str
    doc_type: str
    category: str
    subcategory: str
    version_date: str | None


_SCOPE_KEYWORDS: dict[str, list[str]] = {
    "cross_section": ["design", "guidelines", "street", "road"],
    "intersection": ["intersection", "design", "access"],
    "cycling": ["cycling", "pedestrian", "active"],
    "drainage": ["drainage", "stormwater", "engineering"],
    "street_trees": ["tree", "forestry", "planting", "irrigation"],
    "mobility": ["mobility", "transportation"],
}


def list_applicable_documents(
    scope: str,
    category: str | None = None,
    cfg: Config | None = None,
    repo: Repository | None = None,
) -> list[DocumentReference]:
    """Return docs that should be consulted for the given scope.

    Used by Claude to plan multi-doc queries and avoid missing guidelines.
    """
    if cfg is None:
        cfg = Config.load()
    if repo is None:
        repo = Repository(cfg.db_path)

    all_docs = repo.list_documents(category=category, latest_only=True)

    scope_lower = scope.lower()
    keywords = []
    for k, kws in _SCOPE_KEYWORDS.items():
        if k in scope_lower or any(w in scope_lower for w in kws):
            keywords.extend(kws)

    def _relevance(doc) -> int:
        title_lower = doc["title"].lower()
        return sum(1 for kw in keywords if kw in title_lower)

    scored = sorted(all_docs, key=_relevance, reverse=True)
    results = []
    for doc in scored:
        results.append(
            DocumentReference(
                doc_id=doc["doc_id"],
                title=doc["title"],
                doc_type=doc["doc_type"],
                category=doc["category"],
                subcategory=doc["subcategory"],
                version_date=doc["version_date"],
            )
        )
    return results
