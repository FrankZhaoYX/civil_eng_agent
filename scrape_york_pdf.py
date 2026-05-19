#!/usr/bin/env python3
import argparse
import csv
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
import pdfplumber


def download_pdf(url: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    response = requests.get(url, stream=True, timeout=30)
    response.raise_for_status()
    with open(dest, "wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            if chunk:
                f.write(chunk)
    return dest


def extract_text(pdf_path: Path) -> str:
    text_pages = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            page_text = page.extract_text() or ""
            text_pages.append(f"--- PAGE {page_number} ---\n{page_text}\n")
    return "\n".join(text_pages)


def extract_tables(pdf_path: Path) -> dict:
    tables_by_page = {}
    with pdfplumber.open(pdf_path) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            page_tables = []
            for table in page.extract_tables():
                normalized = [list(map(lambda cell: cell.strip() if cell else "", row)) for row in table]
                page_tables.append(normalized)
            if page_tables:
                tables_by_page[page_number] = page_tables
    return tables_by_page


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9_-]", "_", text.lower()).strip("_")


def write_text_output(text: str, outdir: Path, filename: str):
    out_path = outdir / filename
    outdir.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding="utf-8")
    return out_path


def write_tables(tables_by_page: dict, outdir: Path, base_name: str):
    outdir.mkdir(parents=True, exist_ok=True)
    for page, page_tables in tables_by_page.items():
        for idx, table in enumerate(page_tables, start=1):
            csv_path = outdir / f"{base_name}_page{page}_table{idx}.csv"
            with csv_path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f, quoting=csv.QUOTE_ALL)
                writer.writerows(table)
    return outdir


class HTMLLinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "a":
            return
        attrs = dict(attrs)
        href = attrs.get("href")
        title = attrs.get("title", "")
        if href:
            self.links.append({"href": href, "title": title})


def fetch_html(url: str) -> str:
    headers = {"User-Agent": "Mozilla/5.0"}
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    return response.text


def extract_media_links(page_url: str, filter_substr: str | None = None) -> list[dict]:
    html = fetch_html(page_url)
    parser = HTMLLinkParser()
    parser.feed(html)
    links = []
    for item in parser.links:
        href = item["href"]
        title = item["title"] or ""
        if href.startswith("#") or href.lower().startswith(("mailto:", "javascript:")):
            continue
        full_url = urljoin(page_url, href)
        if not ("/media/" in href or href.lower().endswith(".pdf") or ".pdf" in href.lower() or "download" in href.lower()):
            continue
        if filter_substr and filter_substr.lower() not in full_url.lower() and filter_substr.lower() not in title.lower():
            continue
        links.append({"url": full_url, "title": title.strip(), "href": href})
    return links


def file_extension(url: str, title: str = "") -> str:
    ext = Path(urlparse(url).path).suffix
    if ext:
        return ext
    ext = Path(title).suffix
    return ext if ext else ".pdf"


def is_pdf_url(url: str) -> bool:
    if url.lower().endswith(".pdf"):
        return True
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        response = requests.head(url, allow_redirects=True, timeout=30, headers=headers)
        content_type = response.headers.get("Content-Type", "").lower()
        return "pdf" in content_type
    except requests.RequestException:
        return False


def download_file(url: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    headers = {"User-Agent": "Mozilla/5.0"}
    response = requests.get(url, stream=True, timeout=30, headers=headers)
    response.raise_for_status()
    with open(dest, "wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            if chunk:
                f.write(chunk)
    return dest


def parse_args():
    parser = argparse.ArgumentParser(
        description="Download a York Region PDF and extract text/tables."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--url", help="URL of the PDF to download")
    source.add_argument("--pdf", help="Local PDF path to parse")
    source.add_argument("--page-url", help="Web page URL with PDF/download links")
    parser.add_argument("--match", help="Filter page links by substring in URL or title")
    parser.add_argument("--limit", type=int, default=0, help="Maximum number of page links to process")
    parser.add_argument("--only-pdf", action="store_true", help="Only download links whose content type is PDF")
    parser.add_argument("--outdir", default="dataset", help="Output directory")
    parser.add_argument(
        "--extract",
        choices=["text", "tables", "all", "none"],
        default="all",
        help="What to extract from the PDF",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    outdir = Path(args.outdir)
    downloaded_pdfs = []
    downloaded_files = []

    if args.page_url:
        print(f"Searching page for attachments: {args.page_url}")
        links = extract_media_links(args.page_url, args.match)
        if not links:
            print("No downloadable media links found on the page.")
            return
        if args.limit > 0:
            links = links[: args.limit]

        for idx, link in enumerate(links, start=1):
            print(f"Found link {idx}/{len(links)}: {link['title'] or link['url']}")
            if args.only_pdf and not is_pdf_url(link["url"]):
                print(f"  Skipping non-PDF link: {link['url']}")
                continue
            filename = slugify(link["title"] or Path(urlparse(link["url"]).path).stem)
            if not filename:
                filename = f"attachment_{idx}"
            ext = file_extension(link["url"], link["title"])
            if not filename.lower().endswith(ext.lower()):
                filename += ext
            file_path = outdir / filename
            print(f"  Downloading {link['url']} -> {file_path}")
            downloaded_file = download_file(link["url"], file_path)
            downloaded_files.append(downloaded_file)
            if args.extract != "none" and is_pdf_url(link["url"]):
                downloaded_pdfs.append(downloaded_file)

        if args.extract == "none":
            print("Downloaded page attachments without extraction.")
            print("Done.")
            return

        if not downloaded_pdfs:
            print("No PDFs were downloaded for extraction.")
            return
    elif args.url:
        pdf_name = Path(args.url).name or "downloaded.pdf"
        pdf_path = outdir / pdf_name
        print(f"Downloading PDF from {args.url} to {pdf_path}")
        pdf_path = download_file(args.url, pdf_path)
        downloaded_pdfs = [pdf_path]
    else:
        pdf_path = Path(args.pdf)
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")
        downloaded_pdfs = [pdf_path]

    for pdf_path in downloaded_pdfs:
        base_name = slugify(pdf_path.stem)

        if args.extract in ["text", "all"]:
            print(f"Extracting text from {pdf_path}...")
            extracted_text = extract_text(pdf_path)
            text_output = write_text_output(extracted_text, outdir, f"{base_name}_text.txt")
            print(f"Text written to {text_output}")

        if args.extract in ["tables", "all"]:
            print(f"Extracting tables from {pdf_path}...")
            tables = extract_tables(pdf_path)
            if not tables:
                print(f"No tables detected in {pdf_path}.")
            else:
                tables_out = write_tables(tables, outdir, base_name)
                print(f"Tables written to {tables_out}")

    print("Done.")


if __name__ == "__main__":
    main()
