"""Evaluation harness — runs golden set against a live corpus.db."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from civil_eng_agent.config import Config
from civil_eng_agent.store.repository import Repository
from civil_eng_agent.tools.search import search_guidelines
from eval.metrics import citation_existence, compute_summary

console = Console()
GOLDEN_SET = Path(__file__).parent / "golden_set.jsonl"


def load_golden() -> list[dict]:
    with GOLDEN_SET.open() as f:
        return [json.loads(line) for line in f if line.strip()]


def run_search(item: dict, cfg: Config, repo: Repository) -> dict[str, Any]:
    query = item["query"]
    expected = item["expected"]
    chunks = search_guidelines(query=query, limit=8, cfg=cfg, repo=repo)
    result = {
        "id": item["id"],
        "type": "search",
        "query": query,
        "chunks": [c.model_dump() for c in chunks],
        "citation_existence": citation_existence([c.model_dump() for c in chunks]),
    }
    if "doc_ids" in expected:
        returned_docs = {c.citation.doc_id for c in chunks}
        result["expected_docs_found"] = bool(set(expected["doc_ids"]) & returned_docs)
    result["pass"] = (
        len(chunks) >= expected.get("min_results", 1)
        and result.get("citation_existence", 0) > 0
    )
    return result


def run_eval(cfg: Config | None = None) -> dict[str, Any]:
    if cfg is None:
        cfg = Config.load()
    repo = Repository(cfg.db_path)
    items = load_golden()

    results: list[dict] = []
    for item in items:
        t = item["type"]
        if t == "search":
            results.append(run_search(item, cfg, repo))
        else:
            results.append({"id": item["id"], "type": t, "pass": None, "skipped": True})

    passed = sum(1 for r in results if r.get("pass") is True)
    failed = sum(1 for r in results if r.get("pass") is False)
    skipped = sum(1 for r in results if r.get("skipped"))

    table = Table(title="Eval Results")
    table.add_column("ID")
    table.add_column("Type")
    table.add_column("Pass")
    for r in results:
        status = "[green]✓[/]" if r.get("pass") else ("[yellow]skip[/]" if r.get("skipped") else "[red]✗[/]")
        table.add_row(r["id"], r["type"], status)

    console.print(table)
    console.print(f"\nPassed: {passed} | Failed: {failed} | Skipped: {skipped}")
    summary = compute_summary(results)
    return summary


if __name__ == "__main__":
    summary = run_eval()
    console.print(summary)
