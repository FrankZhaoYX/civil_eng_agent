"""MCP Resources — expose documents and standards via york:// URIs."""
from __future__ import annotations

from civil_eng_agent.config import Config
from civil_eng_agent.store.repository import Repository


def register_resources(mcp, cfg: Config, _repo_unused: Repository) -> None:
    """Register all MCP resource handlers on the FastMCP instance."""
    # Each handler calls _repo() to get a thread-local connection.
    def _repo() -> Repository:
        return Repository(cfg.db_path)

    @mcp.resource("york://{category}/{subcategory}/docs/{doc_id}")
    def get_document(category: str, subcategory: str, doc_id: str) -> str:
        """Full document metadata and first 10 chunks."""
        r = _repo()
        row = r._conn.execute(
            "SELECT * FROM documents WHERE doc_id = ?", (doc_id,)
        ).fetchone()
        if not row:
            return f"Document not found: {doc_id}"
        chunks = r._conn.execute(
            "SELECT chunk_id, section, page, chunk_text FROM chunks WHERE doc_id = ? LIMIT 10",
            (doc_id,),
        ).fetchall()
        parts = [
            f"# {row['title']}",
            f"Category: {row['category']} / {row['subcategory']}",
            f"Type: {row['doc_type']} | Format: {row['format']}",
            f"Version: {row['version_date'] or 'unknown'}",
            "",
            "## First chunks",
        ]
        for c in chunks:
            parts.append(f"[p{c['page']} §{c['section']}] {c['chunk_text'][:300]}")
        return "\n".join(parts)

    @mcp.resource("york://{category}/{subcategory}/docs/{doc_id}/sections/{section_id}")
    def get_section(category: str, subcategory: str, doc_id: str, section_id: str) -> str:
        """Chunks matching a specific section."""
        r = _repo()
        rows = r._conn.execute(
            """
            SELECT chunk_id, section, page, chunk_text FROM chunks
            WHERE doc_id = ? AND section LIKE ?
            LIMIT 20
            """,
            (doc_id, f"%{section_id}%"),
        ).fetchall()
        if not rows:
            return f"No chunks found for doc={doc_id} section~={section_id}"
        parts = [f"# Section: {section_id} in {doc_id}", ""]
        for row in rows:
            parts.append(f"[p{row['page']}] {row['chunk_text']}")
            parts.append("")
        return "\n".join(parts)

    @mcp.resource("york://drawings/{series}/{drawing_no}")
    def get_drawing(series: str, drawing_no: str) -> str:
        """Standard drawing metadata and callouts."""
        import json
        r = _repo()
        row = r._conn.execute(
            "SELECT * FROM standard_drawings WHERE series=? AND drawing_no=? ORDER BY version_date DESC LIMIT 1",
            (series, drawing_no),
        ).fetchone()
        if not row:
            return f"Drawing not found: {series}-{drawing_no}"
        callouts = json.loads(row["callouts"]) if row["callouts"] else []
        return "\n".join([
            f"# {row['series']}-{row['drawing_no']}: {row['title']}",
            f"Applies to: {row['applies_to'] or 'n/a'}",
            f"File: {row['file_path']}",
            f"Version: {row['version_date']}",
            "",
            "## Callouts",
            *callouts,
        ])

    @mcp.resource("york://standards/{road_type}")
    def get_road_type_standards(road_type: str) -> str:
        """Structured summary of all standards for a road type."""
        r = _repo()
        rt_row = r._conn.execute(
            "SELECT * FROM road_types WHERE LOWER(name) = LOWER(?)", (road_type,)
        ).fetchone()
        if not rt_row:
            names = [d[0] for d in r._conn.execute("SELECT name FROM road_types").fetchall()]
            return f"Road type not found: {road_type}. Known: {names}"

        rt_id = rt_row["road_type_id"]
        cs_rows = r._conn.execute(
            "SELECT * FROM cross_section_standards WHERE road_type_id = ?", (rt_id,)
        ).fetchall()
        geo_rows = r._conn.execute(
            "SELECT * FROM geometric_standards WHERE road_type_id = ?", (rt_id,)
        ).fetchall()

        parts = [f"# Standards for {rt_row['name']}", ""]
        if cs_rows:
            parts.append("## Cross-Section")
            for row in cs_rows:
                parts.append(
                    f"- {row['element']}: min={row['min_m']}m typ={row['typical_m']}m max={row['max_m']}m"
                )
        if geo_rows:
            parts.append("")
            parts.append("## Geometric Parameters")
            for row in geo_rows:
                parts.append(f"- {row['parameter']}: {row['value']} {row['unit']}")
        return "\n".join(parts)
