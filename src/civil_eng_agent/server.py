"""FastMCP entry point for the Civil Engineering Design Assistant."""
from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from civil_eng_agent.config import Config
from civil_eng_agent.prompts import register_prompts
from civil_eng_agent.resources import register_resources
from civil_eng_agent.store.repository import Repository
from civil_eng_agent.tools.applicable import list_applicable_documents
from civil_eng_agent.tools.drawings import find_drawing
from civil_eng_agent.tools.lookup import lookup_parameter
from civil_eng_agent.tools.parse import parse_design_pdf
from civil_eng_agent.tools.review import review_design
from civil_eng_agent.tools.search import search_guidelines

mcp = FastMCP(
    "civil-eng-agent",
    instructions=(
        "Civil Engineering Design Assistant for York Region road design. "
        "Answers standards questions, looks up design parameters, and runs compliance checks. "
        "Every claim carries a citation to a specific document, section, and page. "
        "All output is for reference only and requires sealed engineering review (PEO)."
    ),
)

_cfg: Config | None = None


def _get_deps() -> tuple[Config, Repository]:
    global _cfg
    if _cfg is None:
        _cfg = Config.load()
        _cfg.ensure_dirs()
    # Repository is cheap to construct; each call gets a thread-local connection
    return _cfg, Repository(_cfg.db_path)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@mcp.tool()
def search_guidelines_tool(
    query: str,
    road_type: str | None = None,
    topic: str | None = None,
    category: str | None = None,
    subcategory: str | None = None,
    limit: int = 8,
) -> list[dict[str, Any]]:
    """Hybrid semantic + BM25 search over guideline prose.

    Returns up to `limit` chunks, each with citation (doc, section, page).
    Filter by road_type (e.g. "avenue"), topic (e.g. "cross_section"),
    category, or subcategory.
    """
    cfg, repo = _get_deps()
    results = search_guidelines(
        query=query,
        road_type=road_type,
        topic=topic,
        category=category,
        subcategory=subcategory,
        limit=limit,
        cfg=cfg,
        repo=repo,
    )
    return [r.model_dump() for r in results]


@mcp.tool()
def lookup_parameter_tool(
    road_type: str,
    parameter: str,
    conditions: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Deterministic lookup of a design parameter for a given road type.

    Returns value + unit + citation. Raises an error if no match exists in
    the structured standards tables (run `civil-eng-agent ingest --extract` first).
    """
    cfg, repo = _get_deps()
    results = lookup_parameter(
        road_type=road_type, parameter=parameter, conditions=conditions, cfg=cfg, repo=repo
    )
    return [r.model_dump() for r in results]


@mcp.tool()
def find_drawing_tool(
    series: str | None = None,
    topic: str | None = None,
    road_type: str | None = None,
) -> list[dict[str, Any]]:
    """Return matching standard drawings (DS-series, NHF-series) with callouts.

    Filter by series (e.g. "DS-100"), topic keyword, or road type name.
    """
    cfg, repo = _get_deps()
    results = find_drawing(series=series, topic=topic, road_type=road_type, cfg=cfg, repo=repo)
    return [r.model_dump() for r in results]


@mcp.tool()
def list_applicable_documents_tool(
    scope: str,
    category: str | None = None,
) -> list[dict[str, Any]]:
    """Return the set of documents that should be consulted for this scope.

    Use this before running other tools to ensure no relevant guideline is missed.
    """
    cfg, repo = _get_deps()
    results = list_applicable_documents(scope=scope, category=category, cfg=cfg, repo=repo)
    return [r.model_dump() for r in results]


@mcp.tool()
def review_design_tool(
    design: dict[str, Any],
    scope: list[str] | None = None,
) -> dict[str, Any]:
    """Run encoded compliance rules against the design payload.

    design: dict with road_type plus parameter values (lane widths, speeds, etc.)
    Returns a ComplianceReport with per-rule pass/fail/warning and citations.
    Unresolved fields (parameters not in the payload) are listed separately.
    """
    cfg, repo = _get_deps()
    report = review_design(design=design, scope=scope, cfg=cfg, repo=repo)
    return report.model_dump()


@mcp.tool()
def parse_design_pdf_tool(
    file_path: str,
    use_vision: bool = False,
) -> dict[str, Any]:
    """Parse a local design PDF and extract recognisable parameters.

    Returns extracted parameters + confidence scores + list of fields needing
    engineer confirmation. Set use_vision=True to use Claude Vision for
    figure-heavy plan sheets (requires ANTHROPIC_API_KEY; off by default).
    """
    cfg, _ = _get_deps()
    result = parse_design_pdf(file_path=file_path, use_vision=use_vision, cfg=cfg)
    return result.model_dump()


# ---------------------------------------------------------------------------
# Resources + Prompts
# ---------------------------------------------------------------------------

def _register_all() -> None:
    cfg, repo = _get_deps()
    register_resources(mcp, cfg, repo)
    register_prompts(mcp)


_register_all()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def serve() -> None:
    mcp.run()


if __name__ == "__main__":
    serve()
