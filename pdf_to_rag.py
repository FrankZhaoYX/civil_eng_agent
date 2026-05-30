#!/usr/bin/env python3
"""Extract PDFs from the dataset folder and write a RAG-ready JSONL file.

Output schema per chunk:
  id            – unique slug: {doc_id}-p{page}-c{idx}
  doc_id        – kebab-case document identifier
  doc_title     – human-readable document title
  version_date  – ISO date string (YYYY-MM-DD)
  section       – nearest section heading above this chunk, or ""
  page          – 1-based page number
  road_types    – list of detected road-type tags
  topics        – list of detected topic tags
  chunk_text    – chunk content
  is_latest     – always True for fresh ingestion; set False when superseded
"""
import argparse
import json
import re
from pathlib import Path

import pdfplumber


PDF_EXTENSIONS = {".pdf"}

# ---------------------------------------------------------------------------
# Document metadata: map filename stem → (doc_id, doc_title, version_date)
# ---------------------------------------------------------------------------
_DOC_META: dict[str, tuple[str, str, str]] = {
    "designing_great_street_guidelines_part_1": (
        "dgs-part-1",
        "Designing Great Streets Guidelines Part 1",
        "2013-01-01",
    ),
    "designing_great_street_guidelines_part_2": (
        "dgs-part-2",
        "Designing Great Streets Guidelines Part 2",
        "2013-01-01",
    ),
    "road_design_guidelines_-_december_2025": (
        "road-design-guidelines-2025",
        "Road Design Guidelines (December 2025)",
        "2025-12-01",
    ),
    "access_guidelines_for_regional_road": (
        "access-guidelines-2020",
        "Access Guidelines for Regional Roads (2020)",
        "2020-01-01",
    ),
    "detailed_design_guidelines_and_standards": (
        "detailed-design-guidelines",
        "Detailed Design Guidelines and Standards",
        "2010-01-01",
    ),
    "pedestrian_and_cycling_planning_and_design_guidelines_2020_part_1": (
        "cycling-guidelines-2020-part-1",
        "Pedestrian and Cycling Planning and Design Guidelines 2020 Part 1",
        "2020-01-01",
    ),
    "pedestrian_and_cycling_planning_and_design_guidelines_2020_part_2": (
        "cycling-guidelines-2020-part-2",
        "Pedestrian and Cycling Planning and Design Guidelines 2020 Part 2",
        "2020-01-01",
    ),
    "pedestrian_and_cycling_planning_and_design_guidelines_2020_part_3": (
        "cycling-guidelines-2020-part-3",
        "Pedestrian and Cycling Planning and Design Guidelines 2020 Part 3",
        "2020-01-01",
    ),
    "street_tree_and_forest_preservation_guidelines__may_2025": (
        "street-tree-guidelines-2025",
        "Street Tree and Forest Preservation Guidelines (May 2025)",
        "2025-05-01",
    ),
    "irrigation_design_guidelines_-_april_2024_pdf": (
        "irrigation-guidelines-2024",
        "Irrigation Design Guidelines (April 2024)",
        "2024-04-01",
    ),
    "trn_mobility_plan_guidelines_2025_pdf": (
        "mobility-plan-guidelines-2025",
        "Transportation Mobility Plan Guidelines (2025)",
        "2025-01-01",
    ),
}

_FALLBACK_DOC_ID_RE = re.compile(r"[^a-z0-9]+")


def doc_meta(stem: str) -> tuple[str, str, str]:
    meta = _DOC_META.get(stem)
    if meta:
        return meta
    doc_id = _FALLBACK_DOC_ID_RE.sub("-", stem.lower()).strip("-")
    return doc_id, stem.replace("_", " ").title(), "1970-01-01"


# ---------------------------------------------------------------------------
# Road-type tagging
# ---------------------------------------------------------------------------
_ROAD_TYPE_PATTERNS: list[tuple[str, list[str]]] = [
    ("city_centre_street", [r"city[\s\-]centre street", r"city[\s\-]center street"]),
    ("avenue", [r"\bavenue\b"]),
    ("main_street", [r"main street"]),
    ("connector", [r"\bconnector\b"]),
    ("rural_hamlet_road", [r"rural hamlet"]),
    ("rural_road", [r"\brural road\b"]),
]

_ROAD_TYPE_COMPILED = [
    (tag, [re.compile(p, re.IGNORECASE) for p in patterns])
    for tag, patterns in _ROAD_TYPE_PATTERNS
]


def tag_road_types(text: str) -> list[str]:
    tags = []
    for tag, patterns in _ROAD_TYPE_COMPILED:
        if any(p.search(text) for p in patterns):
            tags.append(tag)
    return tags


# ---------------------------------------------------------------------------
# Topic tagging
# ---------------------------------------------------------------------------
_TOPIC_PATTERNS: list[tuple[str, list[str]]] = [
    ("cross_section", [r"cross[\s\-]section", r"travel lane", r"lane width", r"boulevard width"]),
    ("sight_distance", [r"sight distance", r"stopping sight", r"decision sight"]),
    ("cycling", [r"\bcycl", r"cycle track", r"bike lane", r"\bbicycle\b"]),
    ("pedestrian", [r"pedestrian", r"\bsidewalk\b", r"\bwalkway\b", r"accessibility"]),
    ("intersection", [r"intersection", r"turning radius", r"\bcorner\b", r"traffic signal"]),
    ("street_trees", [r"street tree", r"\bplanting\b", r"\bshrub\b", r"\btree species\b", r"\bcanopy\b"]),
    ("drainage", [r"\bdrainage\b", r"storm sewer", r"stormwater", r"runoff"]),
    ("illumination", [r"\billumination\b", r"\blighting\b", r"light standard", r"light pole"]),
    ("pavement_marking", [r"pavement marking", r"lane marking", r"line marking", r"\bstriping\b"]),
    ("access", [r"\bdriveway\b", r"entrance spacing", r"\baccess spacing\b"]),
    ("wayfinding", [r"wayfinding", r"\bsignage\b", r"\bsign\b"]),
    ("irrigation", [r"\birrigation\b", r"watering system", r"drip system"]),
    ("speed", [r"design speed", r"\bspeed limit\b", r"\boperating speed\b"]),
    ("mobility", [r"\bmobility\b", r"transportation network", r"transit"]),
]

_TOPIC_COMPILED = [
    (tag, [re.compile(p, re.IGNORECASE) for p in patterns])
    for tag, patterns in _TOPIC_PATTERNS
]


def tag_topics(text: str) -> list[str]:
    tags = []
    for tag, patterns in _TOPIC_COMPILED:
        if any(p.search(text) for p in patterns):
            tags.append(tag)
    return tags


# ---------------------------------------------------------------------------
# Section heading detection
# ---------------------------------------------------------------------------
# Matches lines like "3.2 Avenue Cross-Section" or "5.0 Implementation"
_SECTION_RE = re.compile(
    r"^(?:"
    r"\d+(?:\.\d+)*\s+[A-Z]"        # numbered: "3.2 Foo"
    r"|[A-Z][A-Z\s\-/&]{4,}$"       # all-caps heading of 5+ chars
    r")",
    re.MULTILINE,
)


def detect_section(text: str, previous: str) -> str:
    """Return the last section heading found in text, or keep previous."""
    matches = _SECTION_RE.findall(text)
    if matches:
        # Take the last match and normalise whitespace
        return re.sub(r"\s+", " ", matches[-1].strip())
    return previous


# ---------------------------------------------------------------------------
# PDF extraction
# ---------------------------------------------------------------------------

def extract_pdf_pages(pdf_path: Path) -> list[dict]:
    pages = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            page_text = page.extract_text() or ""
            pages.append({"page": page_number, "text": page_text.strip()})
    return pages


def extract_pdf_pages_safe(pdf_path: Path) -> list[dict]:
    try:
        return extract_pdf_pages(pdf_path)
    except Exception as exc:
        print(f"  Warning: extraction error for {pdf_path.name}: {exc}")
        return []


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

def normalize_whitespace(text: str) -> str:
    return re.sub(r"[ \t]+", " ", text.replace("\r\n", "\n").strip())


def split_paragraphs(text: str) -> list[str]:
    parts = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
    return parts or [text]


def chunk_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    text = normalize_whitespace(text)
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end].strip())
        start = max(start + 1, end - overlap) if end < len(text) else end
    return [c for c in chunks if c]


# ---------------------------------------------------------------------------
# Build records
# ---------------------------------------------------------------------------

def build_rag_records(
    pdf_path: Path,
    chunk_size: int,
    overlap: int,
    min_chars: int,
) -> list[dict]:
    doc_id, doc_title, version_date = doc_meta(pdf_path.stem)
    pages = extract_pdf_pages_safe(pdf_path)

    records: list[dict] = []
    current_section = ""

    for page in pages:
        raw = normalize_whitespace(page["text"])
        current_section = detect_section(raw, current_section)

        for paragraph in split_paragraphs(raw):
            if len(paragraph) < min_chars:
                continue
            chunks = [paragraph] if len(paragraph) <= chunk_size else chunk_text(paragraph, chunk_size, overlap)
            for idx, chunk in enumerate(chunks, start=1):
                if len(chunk) < min_chars:
                    continue
                records.append(
                    {
                        "id": f"{doc_id}-p{page['page']}-c{idx}",
                        "doc_id": doc_id,
                        "doc_title": doc_title,
                        "version_date": version_date,
                        "section": current_section,
                        "page": page["page"],
                        "road_types": tag_road_types(chunk),
                        "topics": tag_topics(chunk),
                        "chunk_text": chunk,
                        "is_latest": True,
                    }
                )
    return records


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def write_jsonl(records: list[dict], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract PDFs from the dataset folder to a RAG-ready JSONL file."
    )
    parser.add_argument("--source", default="dataset", help="Folder containing PDF files")
    parser.add_argument("--output", default="dataset/rag.jsonl", help="Output JSONL path")
    parser.add_argument("--chunk-size", type=int, default=1200, help="Max chars per chunk")
    parser.add_argument("--overlap", type=int, default=200, help="Char overlap between chunks")
    parser.add_argument("--min-chars", type=int, default=80, help="Skip chunks shorter than this")
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Remove CSV/TXT/JSONL/.DS_Store files from source before running",
    )
    return parser.parse_args()


def clean_dataset_folder(source_dir: Path) -> list[str]:
    removed = []
    for path in source_dir.iterdir():
        if not path.is_file():
            continue
        if path.suffix.lower() in {".txt", ".csv", ".jsonl", ".json"} or path.name == ".DS_Store":
            path.unlink()
            removed.append(path.name)
    return removed


def main() -> None:
    args = parse_args()
    source_dir = Path(args.source)
    output_path = Path(args.output)

    if not source_dir.is_dir():
        raise FileNotFoundError(f"Source folder not found: {source_dir}")

    if args.clean:
        removed = clean_dataset_folder(source_dir)
        print(f"Removed: {removed}" if removed else "Nothing to clean.")

    pdf_files = sorted(p for p in source_dir.iterdir() if p.is_file() and p.suffix.lower() in PDF_EXTENSIONS)
    if not pdf_files:
        raise FileNotFoundError(f"No PDF files found in {source_dir}")

    print(f"Found {len(pdf_files)} PDF(s) in {source_dir}")
    all_records: list[dict] = []

    for pdf_path in pdf_files:
        print(f"Processing {pdf_path.name} ...")
        records = build_rag_records(
            pdf_path,
            chunk_size=args.chunk_size,
            overlap=args.overlap,
            min_chars=args.min_chars,
        )
        all_records.extend(records)
        print(f"  -> {len(records)} chunks")

    write_jsonl(all_records, output_path)
    print(f"\nWrote {len(all_records)} records to {output_path}")

    # Summary stats
    road_type_counts: dict[str, int] = {}
    topic_counts: dict[str, int] = {}
    for r in all_records:
        for t in r["road_types"]:
            road_type_counts[t] = road_type_counts.get(t, 0) + 1
        for t in r["topics"]:
            topic_counts[t] = topic_counts.get(t, 0) + 1

    if road_type_counts:
        print("\nRoad-type tag counts:")
        for k, v in sorted(road_type_counts.items(), key=lambda x: -x[1]):
            print(f"  {k}: {v}")
    if topic_counts:
        print("\nTopic tag counts:")
        for k, v in sorted(topic_counts.items(), key=lambda x: -x[1]):
            print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
