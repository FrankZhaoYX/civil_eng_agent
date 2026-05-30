"""lookup_parameter tool: deterministic SQL lookup against structured standards."""
from __future__ import annotations

from pydantic import BaseModel

from civil_eng_agent.citations import Citation
from civil_eng_agent.config import Config
from civil_eng_agent.store.repository import Repository


class ParameterResult(BaseModel):
    road_type: str
    parameter: str
    value: float
    unit: str
    conditions: str | None
    citation: Citation


def lookup_parameter(
    road_type: str,
    parameter: str,
    conditions: dict | None = None,
    cfg: Config | None = None,
    repo: Repository | None = None,
) -> list[ParameterResult]:
    """Deterministic SQL lookup for road-design parameters.

    Raises ValueError if no match found (ensures claims have citations).
    """
    if cfg is None:
        cfg = Config.load()
    if repo is None:
        repo = Repository(cfg.db_path)

    rows = repo.lookup_parameter(road_type, parameter, conditions)

    if not rows:
        raise ValueError(
            f"No standard found for road_type={road_type!r}, parameter={parameter!r}. "
            "Run `civil-eng-agent ingest --extract` to populate structured standards."
        )

    results = []
    for row in rows:
        doc_row = repo._conn.execute(
            "SELECT * FROM documents WHERE doc_id = ?", (row["source_doc"],)
        ).fetchone()
        cat = doc_row["category"] if doc_row else ""
        subcat = doc_row["subcategory"] if doc_row else ""
        title = doc_row["title"] if doc_row else row["source_doc"]

        results.append(
            ParameterResult(
                road_type=row["road_type_name"],
                parameter=row["parameter"],
                value=row["value"],
                unit=row["unit"],
                conditions=row["conditions"],
                citation=Citation(
                    category=cat,
                    subcategory=subcat,
                    doc_id=row["source_doc"],
                    doc_title=title,
                    section=row["source_section"],
                    page=row["source_page"],
                    version_date=row["version_date"],
                ),
            )
        )

    return results
