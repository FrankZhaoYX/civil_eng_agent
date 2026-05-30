#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "httpx>=0.27",
#   "beautifulsoup4>=4.12",
#   "pyyaml>=6.0",
#   "rich>=13.0",
# ]
# ///
"""Phase 0 scraper: download York Region documents per config/sources.yaml.

Usage:
    uv run scripts/scrape_york.py
    uv run scripts/scrape_york.py --source "Construction"
    uv run scripts/scrape_york.py --dry-run
    uv run scripts/scrape_york.py --category "Land Development"
"""
import argparse
import hashlib
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
import yaml
from bs4 import BeautifulSoup
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

REPO_ROOT = Path(__file__).parent.parent
CONFIG_PATH = REPO_ROOT / "config" / "sources.yaml"
DATA_RAW = REPO_ROOT / "data" / "raw"
USER_AGENT = "civil-eng-agent/0.1 (York Region design standards scraper; contact: github.com/civil-eng-agent)"
REQUEST_DELAY_S = 1.0
SUPPORTED_MEDIA_TYPES = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/msword": ".doc",
}

console = Console()


def load_sources(config_path: Path) -> list[dict]:
    with config_path.open() as f:
        cfg = yaml.safe_load(f)
    return cfg.get("sources", [])


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9_-]+", "_", text.lower()).strip("_")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def load_manifest(manifest_path: Path) -> dict:
    if manifest_path.exists():
        with manifest_path.open() as f:
            return json.load(f)
    return {}


def save_manifest(manifest_path: Path, data: dict) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with manifest_path.open("w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def fetch_page(client: httpx.Client, url: str) -> str:
    resp = client.get(url, follow_redirects=True)
    resp.raise_for_status()
    return resp.text


def extract_doc_links(page_url: str, html: str) -> list[dict]:
    """Extract PDF/DOCX links from a York Region page."""
    soup = BeautifulSoup(html, "html.parser")
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith("#") or href.lower().startswith(("mailto:", "javascript:")):
            continue
        full_url = urljoin(page_url, href)
        parsed = urlparse(full_url)
        # York Region docs live under /media/ or end with download param
        if not ("/media/" in parsed.path or "download" in parsed.query):
            continue
        anchor_text = a.get_text(strip=True) or a.get("title", "") or ""
        links.append({"url": full_url, "anchor_text": anchor_text})
    return links


def probe_link(client: httpx.Client, url: str) -> dict | None:
    """HEAD request to get content-type, size, last-modified."""
    try:
        resp = client.head(url, follow_redirects=True)
        resp.raise_for_status()
        ct = resp.headers.get("content-type", "").split(";")[0].strip()
        if ct not in SUPPORTED_MEDIA_TYPES:
            # Some York URLs redirect to the actual file; try GET first 512 bytes
            resp2 = client.get(url, follow_redirects=True, headers={"Range": "bytes=0-511"})
            ct = resp2.headers.get("content-type", "").split(";")[0].strip()
            if ct not in SUPPORTED_MEDIA_TYPES:
                return None
        size = int(resp.headers.get("content-length", 0))
        last_mod = resp.headers.get("last-modified", "")
        return {"content_type": ct, "size_bytes": size, "last_modified": last_mod}
    except httpx.HTTPError:
        return None


def derive_filename(url: str, anchor_text: str, content_type: str) -> str:
    ext = SUPPORTED_MEDIA_TYPES.get(content_type, ".pdf")
    base = slugify(anchor_text) if anchor_text else slugify(Path(urlparse(url).path).stem)
    if not base:
        base = "document"
    if not base.endswith(ext):
        base += ext
    return base


def download_file(client: httpx.Client, url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with client.stream("GET", url, follow_redirects=True) as resp:
        resp.raise_for_status()
        with dest.open("wb") as f:
            for chunk in resp.iter_bytes(65536):
                f.write(chunk)


def scrape_source(
    client: httpx.Client,
    source: dict,
    dry_run: bool,
    force: bool,
) -> dict:
    category = source["category"]
    subcategory = source["subcategory"]
    url = source["url"]

    dest_dir = DATA_RAW / category / subcategory
    manifest_path = dest_dir / "_manifest.json"
    existing = load_manifest(manifest_path)
    existing_files = {f["url"]: f for f in existing.get("files", [])}

    console.print(f"  [cyan]Fetching[/] {url}")
    try:
        html = fetch_page(client, url)
    except httpx.HTTPError as e:
        console.print(f"  [red]Error fetching page:[/] {e}")
        return {}

    links = extract_doc_links(url, html)
    console.print(f"  Found {len(links)} candidate link(s)")

    files_meta: list[dict] = []
    downloaded = skipped = errors = 0

    for link in links:
        doc_url = link["url"]
        anchor = link["anchor_text"]
        time.sleep(REQUEST_DELAY_S)

        info = probe_link(client, doc_url)
        if not info:
            continue

        filename = derive_filename(doc_url, anchor, info["content_type"])
        dest_path = dest_dir / filename

        # Check if already downloaded and unchanged
        if not force and doc_url in existing_files:
            prev = existing_files[doc_url]
            if dest_path.exists() and prev.get("last_modified") == info["last_modified"] and info["last_modified"]:
                console.print(f"    [dim]skip (unchanged)[/] {filename}")
                files_meta.append(prev)
                skipped += 1
                continue

        if dry_run:
            console.print(f"    [yellow]dry-run[/] would download: {filename} ({info['size_bytes']:,} bytes)")
            downloaded += 1
            continue

        console.print(f"    [green]downloading[/] {filename}")
        try:
            download_file(client, doc_url, dest_path)
            sha = sha256_file(dest_path)
            meta = {
                "url": doc_url,
                "anchor_text": anchor,
                "filename": filename,
                "size_bytes": dest_path.stat().st_size,
                "sha256": sha,
                "content_type": info["content_type"],
                "last_modified": info["last_modified"],
                "downloaded_at": datetime.now(timezone.utc).isoformat(),
            }
            files_meta.append(meta)
            downloaded += 1
        except httpx.HTTPError as e:
            console.print(f"    [red]error:[/] {e}")
            errors += 1

    if not dry_run:
        manifest = {
            "category": category,
            "subcategory": subcategory,
            "source_url": url,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "files": files_meta,
        }
        save_manifest(manifest_path, manifest)

    console.print(
        f"  [bold]Done:[/] {downloaded} downloaded, {skipped} skipped, {errors} errors"
    )
    return {"downloaded": downloaded, "skipped": skipped, "errors": errors}


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape York Region document pages")
    parser.add_argument("--source", help="Filter sources by substring in subcategory")
    parser.add_argument("--category", help="Filter sources by category")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be downloaded")
    parser.add_argument("--force", action="store_true", help="Re-download even if unchanged")
    args = parser.parse_args()

    if not CONFIG_PATH.exists():
        console.print(f"[red]Config not found:[/] {CONFIG_PATH}")
        sys.exit(1)

    sources = load_sources(CONFIG_PATH)

    if args.category:
        sources = [s for s in sources if args.category.lower() in s["category"].lower()]
    if args.source:
        sources = [s for s in sources if args.source.lower() in s["subcategory"].lower()]

    if not sources:
        console.print("[yellow]No matching sources.[/]")
        sys.exit(0)

    console.print(f"[bold]Scraping {len(sources)} source(s)[/]")

    with httpx.Client(
        headers={"User-Agent": USER_AGENT},
        timeout=60.0,
        follow_redirects=True,
    ) as client:
        for source in sources:
            console.rule(f"[bold]{source['category']} / {source['subcategory']}")
            scrape_source(client, source, dry_run=args.dry_run, force=args.force)

    console.print("[bold green]All done.[/]")


if __name__ == "__main__":
    main()
