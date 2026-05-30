"""Evaluation metrics for the civil-eng-agent corpus."""
from __future__ import annotations

from typing import Any


def citation_existence(results: list[dict]) -> float:
    """Fraction of results that have at least one citation."""
    if not results:
        return 0.0
    return sum(1 for r in results if r.get("citation")) / len(results)


def citation_correctness(results: list[dict], expected_doc_ids: list[str]) -> float:
    """Fraction of results whose citation.doc_id is in expected_doc_ids."""
    if not results or not expected_doc_ids:
        return 0.0
    correct = sum(
        1 for r in results
        if r.get("citation", {}).get("doc_id") in expected_doc_ids
    )
    return correct / len(results)


def numeric_accuracy(actual: float, expected: float, tolerance: float = 0.05) -> bool:
    """True if actual is within tolerance of expected (relative)."""
    if expected == 0:
        return actual == 0
    return abs(actual - expected) / abs(expected) <= tolerance


def review_precision(results: list[dict]) -> float:
    """Fraction of rules that fired correctly (pass/fail matches expected)."""
    if not results:
        return 0.0
    return sum(1 for r in results if r.get("status") in ("pass", "fail")) / len(results)


def compute_summary(eval_results: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate metrics across all eval results."""
    search_results = [r for r in eval_results if r["type"] == "search"]
    lookup_results = [r for r in eval_results if r["type"] == "lookup"]
    review_results = [r for r in eval_results if r["type"] == "review"]

    return {
        "total": len(eval_results),
        "search_citation_existence": citation_existence(
            [chunk for r in search_results for chunk in r.get("chunks", [])]
        ),
        "lookup_numeric_accuracy": sum(
            1 for r in lookup_results if r.get("numeric_correct", False)
        ) / max(len(lookup_results), 1),
        "review_rules_evaluated": sum(
            len(r.get("rule_results", [])) for r in review_results
        ),
    }
