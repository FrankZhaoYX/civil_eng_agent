"""LLM-assisted structured extraction for Land Development documents (Phase 2+).

Extracts cross-section standards and geometric parameters from guideline PDFs
and inserts them into the structured tables in corpus.db.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from civil_eng_agent.config import Config
    from civil_eng_agent.store.repository import Repository

_CROSS_SECTION_PROMPT = """
You are a civil engineering standards parser. Given the following text from a York Region
road design guideline, extract all cross-section width standards.

For each entry return a JSON object with:
  road_type, element, position (optional), min_m (float or null),
  typical_m (float or null), max_m (float or null), conditions (str or null),
  source_section (str), source_page (int or null)

Return a JSON array. If nothing can be extracted, return [].

Text:
{text}
""".strip()

_GEOMETRIC_PROMPT = """
You are a civil engineering standards parser. Given the following text from a York Region
road design guideline, extract all geometric design parameters (speeds, grades, radii, etc.).

For each entry return a JSON object with:
  road_type, parameter, value (float), unit (str), conditions (str or null),
  source_section (str), source_page (int or null)

Return a JSON array. If nothing can be extracted, return [].

Text:
{text}
""".strip()


def extract_structured(
    doc_id: str,
    chunks: list[dict],
    repo: "Repository",
    cfg: "Config",
    version_date: str,
    source_doc: str,
) -> None:
    """Run LLM extraction on chunks tagged with cross_section or speed topics."""
    import anthropic

    if not cfg.anthropic_api_key:
        print("  Skipping structured extraction: no ANTHROPIC_API_KEY")
        return

    client = anthropic.Anthropic(api_key=cfg.anthropic_api_key)

    cs_chunks = [c for c in chunks if "cross_section" in (c.get("topics") or [])]
    geo_chunks = [c for c in chunks if "speed" in (c.get("topics") or [])]

    def _call(prompt_template: str, text: str) -> list[dict]:
        msg = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt_template.format(text=text[:4000])}],
        )
        raw = msg.content[0].text.strip()
        try:
            start = raw.find("[")
            end = raw.rfind("]") + 1
            return json.loads(raw[start:end]) if start >= 0 else []
        except json.JSONDecodeError:
            return []

    for chunk in cs_chunks[:20]:
        rows = _call(_CROSS_SECTION_PROMPT, chunk["chunk_text"])
        for row in rows:
            _upsert_road_type_and_cross_section(repo, row, source_doc, version_date)

    for chunk in geo_chunks[:20]:
        rows = _call(_GEOMETRIC_PROMPT, chunk["chunk_text"])
        for row in rows:
            _upsert_road_type_and_geometric(repo, row, source_doc, version_date)


def _upsert_road_type_and_cross_section(
    repo: "Repository", row: dict, source_doc: str, version_date: str
) -> None:
    road_type_name = row.get("road_type", "").strip()
    if not road_type_name:
        return
    rt_id = _ensure_road_type(repo, road_type_name, source_doc, version_date)
    repo._conn.execute(
        """
        INSERT INTO cross_section_standards
          (road_type_id, element, position, min_m, typical_m, max_m,
           conditions, source_doc, source_section, source_page, version_date)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            rt_id,
            row.get("element", ""),
            row.get("position"),
            row.get("min_m"),
            row.get("typical_m"),
            row.get("max_m"),
            row.get("conditions"),
            source_doc,
            row.get("source_section", ""),
            row.get("source_page"),
            version_date,
        ),
    )
    repo._conn.commit()


def _upsert_road_type_and_geometric(
    repo: "Repository", row: dict, source_doc: str, version_date: str
) -> None:
    road_type_name = row.get("road_type", "").strip()
    if not road_type_name or row.get("value") is None:
        return
    rt_id = _ensure_road_type(repo, road_type_name, source_doc, version_date)
    repo._conn.execute(
        """
        INSERT INTO geometric_standards
          (road_type_id, parameter, value, unit, conditions,
           source_doc, source_section, source_page, version_date)
        VALUES (?,?,?,?,?,?,?,?,?)
        """,
        (
            rt_id,
            row.get("parameter", ""),
            float(row["value"]),
            row.get("unit", ""),
            row.get("conditions"),
            source_doc,
            row.get("source_section", ""),
            row.get("source_page"),
            version_date,
        ),
    )
    repo._conn.commit()


def _ensure_road_type(
    repo: "Repository", name: str, source_doc: str, version_date: str
) -> int:
    row = repo._conn.execute(
        "SELECT road_type_id FROM road_types WHERE LOWER(name) = LOWER(?)", (name,)
    ).fetchone()
    if row:
        return row[0]
    cur = repo._conn.execute(
        "INSERT INTO road_types (name, source_doc, version_date) VALUES (?,?,?)",
        (name, source_doc, version_date),
    )
    repo._conn.commit()
    return cur.lastrowid
