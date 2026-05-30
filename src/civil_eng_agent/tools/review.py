"""review_design tool: run encoded compliance rules against a design payload."""
from __future__ import annotations

import json
import operator as _op
from typing import Any

from pydantic import BaseModel

from civil_eng_agent.citations import Citation
from civil_eng_agent.config import Config
from civil_eng_agent.store.repository import Repository

DISCLAIMER = (
    "For reference only. Final designs require sealed engineering review "
    "by a Professional Engineer licensed in Ontario (PEO)."
)

_OPS = {
    ">=": _op.ge,
    "<=": _op.le,
    ">": _op.gt,
    "<": _op.lt,
    "==": _op.eq,
}


class RuleResult(BaseModel):
    rule_id: str
    description: str
    status: str  # "pass" | "fail" | "warning" | "skip"
    severity: str
    expected: str | None
    actual: str | None
    citation: Citation


class ComplianceReport(BaseModel):
    design: dict[str, Any]
    scope_consulted: list[dict]
    results: list[RuleResult]
    unresolved_fields: list[str]
    disclaimer: str = DISCLAIMER


def review_design(
    design: dict[str, Any],
    scope: list[str] | None = None,
    cfg: Config | None = None,
    repo: Repository | None = None,
) -> ComplianceReport:
    """Run compliance rules against the design payload.

    design keys: road_type, travel_lane_width_m, shoulder_width_m,
                 sidewalk_width_m, design_speed_kmh, etc.
    """
    if cfg is None:
        cfg = Config.load()
    if repo is None:
        repo = Repository(cfg.db_path)

    road_type = design.get("road_type", "")
    rules = repo.list_compliance_rules()

    # Determine road_type_id if known
    rt_row = repo._conn.execute(
        "SELECT road_type_id FROM road_types WHERE LOWER(name) = LOWER(?)", (road_type,)
    ).fetchone()
    rt_id = rt_row[0] if rt_row else None
    if rt_id:
        rules = repo.list_compliance_rules(road_type_id=rt_id)

    results: list[RuleResult] = []
    unresolved: list[str] = []

    for rule in rules:
        logic = json.loads(rule["check_logic"])
        param = logic.get("parameter")
        op_str = logic.get("operator")
        threshold = logic.get("threshold")
        unit = logic.get("unit", "")

        if param not in design:
            unresolved.append(param)
            results.append(
                RuleResult(
                    rule_id=rule["rule_id"],
                    description=rule["description"],
                    status="skip",
                    severity=rule["severity"],
                    expected=f"{op_str} {threshold} {unit}".strip(),
                    actual=None,
                    citation=_make_citation(rule, repo),
                )
            )
            continue

        actual_val = design[param]
        op_fn = _OPS.get(op_str)
        if op_fn is None or not op_fn(actual_val, threshold):
            status = "fail" if rule["severity"] == "must" else "warning"
        else:
            status = "pass"

        results.append(
            RuleResult(
                rule_id=rule["rule_id"],
                description=rule["description"],
                status=status,
                severity=rule["severity"],
                expected=f"{op_str} {threshold} {unit}".strip(),
                actual=f"{actual_val} {unit}".strip(),
                citation=_make_citation(rule, repo),
            )
        )

    scope_consulted = _scope_docs(repo, road_type)

    return ComplianceReport(
        design=design,
        scope_consulted=scope_consulted,
        results=results,
        unresolved_fields=list(dict.fromkeys(unresolved)),
    )


def _make_citation(rule, repo) -> Citation:
    doc_row = repo._conn.execute(
        "SELECT * FROM documents WHERE doc_id = ?", (rule["source_doc"],)
    ).fetchone()
    return Citation(
        category=doc_row["category"] if doc_row else "",
        subcategory=doc_row["subcategory"] if doc_row else "",
        doc_id=rule["source_doc"],
        doc_title=doc_row["title"] if doc_row else rule["source_doc"],
        section=rule["source_section"],
        page=rule["source_page"],
        version_date=rule["version_date"],
    )


def _scope_docs(repo, road_type: str) -> list[dict]:
    docs = repo.list_documents()
    return [
        {"category": d["category"], "subcategory": d["subcategory"], "doc": d["title"]}
        for d in docs
    ]
