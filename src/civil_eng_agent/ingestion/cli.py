"""Ingestion CLI: scrape, ingest, and manage sources."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import click
import yaml
from rich.console import Console
from rich.table import Table

from civil_eng_agent.config import REPO_ROOT, Config
from civil_eng_agent.ingestion.chunk_embed import embed_texts
from civil_eng_agent.ingestion.classifiers import get_classifier
from civil_eng_agent.ingestion.parse_docx import parse_docx_chunks
from civil_eng_agent.ingestion.parse_pdf import parse_pdf_chunks
from civil_eng_agent.store.repository import Repository

console = Console()


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9-]+", "-", text.lower()).strip("-")


def doc_id_from_file(category: str, subcategory: str, filename: str) -> str:
    stem = Path(filename).stem
    return slugify(stem)


# ---------------------------------------------------------------------------
# CLI root
# ---------------------------------------------------------------------------

@click.group()
def cli() -> None:
    """Civil Engineering Agent — data management CLI."""


# ---------------------------------------------------------------------------
# scrape
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--source", default=None, help="Filter by subcategory substring")
@click.option("--category", default=None, help="Filter by category substring")
@click.option("--dry-run", is_flag=True)
@click.option("--force", is_flag=True, help="Re-download even if unchanged")
def scrape(source: str | None, category: str | None, dry_run: bool, force: bool) -> None:
    """Phase 0: scrape York Region pages and download documents."""
    script = REPO_ROOT / "scripts" / "scrape_york.py"
    cmd = [sys.executable, str(script)]
    if source:
        cmd += ["--source", source]
    if category:
        cmd += ["--category", category]
    if dry_run:
        cmd.append("--dry-run")
    if force:
        cmd.append("--force")
    subprocess.run(cmd, check=True)


# ---------------------------------------------------------------------------
# ingest
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--category", default=None, help="Only ingest this category")
@click.option("--subcategory", default=None, help="Only ingest this subcategory")
@click.option("--doc", default=None, help="Only ingest this doc_id")
@click.option("--extract", is_flag=True, help="Run LLM structured extraction (Phase 2+)")
@click.option("--no-embed", is_flag=True, help="Skip embedding (useful for dev)")
@click.option("--status", is_flag=True, help="Show ingestion status and exit")
@click.option("--validate", is_flag=True, help="Validate citation resolvability and exit")
def ingest(
    category: str | None,
    subcategory: str | None,
    doc: str | None,
    extract: bool,
    no_embed: bool,
    status: bool,
    validate: bool,
) -> None:
    """Phase 1+: parse raw files and populate corpus.db."""
    cfg = Config.load()
    cfg.ensure_dirs()
    repo = Repository(cfg.db_path)

    if status:
        _show_status(repo)
        return

    if validate:
        _validate(repo)
        return

    raw_root = cfg.data_raw_dir

    # Also accept PDFs from legacy dataset/ folder
    fallback_dirs: list[Path] = []
    legacy = REPO_ROOT / "dataset"
    if legacy.is_dir():
        fallback_dirs.append(legacy)

    categories = _discover_categories(raw_root, category, subcategory)

    if not categories and fallback_dirs:
        console.print("[yellow]No data/raw sources found; trying dataset/ fallback[/]")
        categories = [("Land Development", "Construction Design Guidelines and Standards", fallback_dirs[0])]

    if not categories:
        console.print("[red]No data to ingest. Run `civil-eng-agent scrape` first.[/]")
        return

    for cat, subcat, source_dir in categories:
        console.rule(f"[bold]{cat} / {subcat}")
        manifest_path = source_dir / "_manifest.json"
        manifest = _load_manifest(manifest_path, cat, subcat)

        files = _discover_files(source_dir)
        if not files:
            console.print("  No PDF/DOCX files found.")
            continue

        classify = get_classifier(cat, subcat)

        for file_path in files:
            if doc and slugify(file_path.stem) != doc:
                continue
            _ingest_file(file_path, cat, subcat, manifest, classify, repo, cfg, no_embed, extract)

    console.print("[bold green]Ingestion complete.[/]")
    _show_status(repo)


def _discover_categories(
    raw_root: Path,
    category_filter: str | None,
    subcat_filter: str | None,
) -> list[tuple[str, str, Path]]:
    results = []
    if not raw_root.is_dir():
        return results
    for cat_dir in sorted(raw_root.iterdir()):
        if not cat_dir.is_dir():
            continue
        if category_filter and category_filter.lower() not in cat_dir.name.lower():
            continue
        for subcat_dir in sorted(cat_dir.iterdir()):
            if not subcat_dir.is_dir():
                continue
            if subcat_filter and subcat_filter.lower() not in subcat_dir.name.lower():
                continue
            results.append((cat_dir.name, subcat_dir.name, subcat_dir))
    return results


def _discover_files(directory: Path) -> list[Path]:
    return sorted(
        p for p in directory.iterdir()
        if p.is_file() and p.suffix.lower() in {".pdf", ".docx"}
    )


def _load_manifest(path: Path, category: str, subcategory: str) -> dict:
    if path.exists():
        with path.open() as f:
            return json.load(f)
    # Synthesize minimal manifest for legacy dataset/ usage
    return {"category": category, "subcategory": subcategory, "files": []}


def _ingest_file(
    file_path: Path,
    category: str,
    subcategory: str,
    manifest: dict,
    classify,
    repo: Repository,
    cfg: Config,
    no_embed: bool,
    run_extract: bool,
) -> None:
    filename = file_path.name
    doc_id = slugify(file_path.stem)
    fmt = file_path.suffix.lower().lstrip(".")
    doc_type = classify(filename)

    # SHA256
    h = hashlib.sha256()
    with file_path.open("rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    sha = h.hexdigest()

    # Find metadata from manifest
    file_meta = next(
        (m for m in manifest.get("files", []) if m.get("filename") == filename),
        {},
    )
    source_url = file_meta.get("url") or manifest.get("source_url", "")
    version_date = None

    console.print(f"  [cyan]{filename}[/] → doc_id=[bold]{doc_id}[/] type=[bold]{doc_type}[/]")

    # Parse chunks
    if fmt == "pdf":
        chunks = parse_pdf_chunks(file_path, doc_id)
    elif fmt == "docx":
        chunks = parse_docx_chunks(file_path, doc_id)
    else:
        console.print(f"    [yellow]Skipping unsupported format: {fmt}[/]")
        return

    console.print(f"    {len(chunks)} chunks parsed")

    # Upsert document row
    repo.upsert_document({
        "doc_id": doc_id,
        "category": category,
        "subcategory": subcategory,
        "title": _title_from_stem(file_path.stem),
        "doc_type": doc_type,
        "source_url": source_url,
        "filename": str(file_path.relative_to(REPO_ROOT)),
        "format": fmt,
        "version_date": version_date,
        "sha256": sha,
        "ingested_at": datetime.now(timezone.utc).isoformat(),
        "is_latest": 1,
    })

    # Replace existing chunks
    repo.delete_chunks_for_doc(doc_id)
    chunk_ids = repo.insert_chunks(chunks)
    console.print(f"    {len(chunk_ids)} chunks stored")

    # Embed
    if not no_embed and repo.has_vec():
        texts = [c["chunk_text"] for c in chunks]
        console.print(f"    Embedding {len(texts)} chunks via {cfg.embed.provider}...")
        try:
            vecs = embed_texts(texts, cfg)
            repo.upsert_embeddings(list(zip(chunk_ids, vecs)))
            console.print(f"    {len(vecs)} embeddings stored")
        except Exception as exc:
            console.print(f"    [yellow]Embedding failed: {exc}[/]")

    # Structured extraction (Phase 2+)
    if run_extract:
        from civil_eng_agent.ingestion.extractors.land_development import extract_structured
        extract_structured(doc_id, chunks, repo, cfg, version_date or "1970-01-01", doc_id)


def _title_from_stem(stem: str) -> str:
    return stem.replace("_", " ").replace("-", " ").title()


def _show_status(repo: Repository) -> None:
    stats = repo.stats()
    table = Table(title="Corpus Status")
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    for k, v in stats.items():
        table.add_row(str(k), str(v))
    console.print(table)


def _validate(repo: Repository) -> None:
    console.print("[bold]Validating citations...[/]")
    # Check that every chunk has a resolvable doc_id
    rows = repo._conn.execute(
        """
        SELECT c.chunk_id, c.doc_id FROM chunks c
        LEFT JOIN documents d ON d.doc_id = c.doc_id
        WHERE d.doc_id IS NULL
        """
    ).fetchall()
    if rows:
        console.print(f"[red]{len(rows)} orphaned chunks (no matching document)[/]")
        for r in rows[:10]:
            console.print(f"  chunk_id={r[0]} doc_id={r[1]}")
    else:
        console.print("[green]All chunks have valid doc references.[/]")


# ---------------------------------------------------------------------------
# sources
# ---------------------------------------------------------------------------

@cli.group()
def sources() -> None:
    """Manage config/sources.yaml."""


@sources.command("list")
def sources_list() -> None:
    """Show current source configuration."""
    cfg = Config.load()
    with cfg.sources_yaml.open() as f:
        data = yaml.safe_load(f)
    sources_data = data.get("sources", [])
    table = Table(title="Sources")
    table.add_column("Category")
    table.add_column("Subcategory")
    table.add_column("URL")
    for s in sources_data:
        table.add_row(s["category"], s["subcategory"], s["url"])
    console.print(table)


@sources.command("add")
@click.option("--category", required=True)
@click.option("--subcategory", required=True)
@click.option("--url", required=True)
def sources_add(category: str, subcategory: str, url: str) -> None:
    """Append a new source to config/sources.yaml."""
    cfg = Config.load()
    with cfg.sources_yaml.open() as f:
        data = yaml.safe_load(f) or {"sources": []}
    data.setdefault("sources", []).append(
        {"category": category, "subcategory": subcategory, "url": url}
    )
    with cfg.sources_yaml.open("w") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True)
    console.print(f"[green]Added:[/] {category} / {subcategory}")
