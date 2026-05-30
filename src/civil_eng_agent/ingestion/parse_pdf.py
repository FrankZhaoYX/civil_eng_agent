"""PDF parsing: text extraction, table extraction, section detection, tagging."""
from __future__ import annotations

import re
from pathlib import Path

import pdfplumber


# Road-type tagging patterns
_ROAD_TYPES: list[tuple[str, list[str]]] = [
    ("city_centre_street", [r"city[\s\-]centre street", r"city[\s\-]center street"]),
    ("avenue", [r"\bavenue\b"]),
    ("main_street", [r"main street"]),
    ("connector", [r"\bconnector\b"]),
    ("rural_hamlet_road", [r"rural hamlet"]),
    ("rural_road", [r"\brural road\b"]),
]

_TOPIC_PATTERNS: list[tuple[str, list[str]]] = [
    ("cross_section", [r"cross[\s\-]section", r"travel lane", r"lane width", r"boulevard"]),
    ("sight_distance", [r"sight distance", r"stopping sight", r"decision sight"]),
    ("cycling", [r"\bcycl", r"cycle track", r"bike lane", r"\bbicycle\b"]),
    ("pedestrian", [r"pedestrian", r"\bsidewalk\b", r"\bwalkway\b", r"accessibility"]),
    ("intersection", [r"intersection", r"turning radius", r"traffic signal"]),
    ("street_trees", [r"street tree", r"\bplanting\b", r"\btree species\b", r"\bcanopy\b"]),
    ("drainage", [r"\bdrainage\b", r"storm sewer", r"stormwater", r"runoff"]),
    ("illumination", [r"\billumination\b", r"\blighting\b", r"light standard"]),
    ("pavement_marking", [r"pavement marking", r"lane marking", r"\bstriping\b"]),
    ("access", [r"\bdriveway\b", r"entrance spacing", r"\baccess spacing\b"]),
    ("speed", [r"design speed", r"\bspeed limit\b", r"operating speed"]),
    ("mobility", [r"\bmobility\b", r"transportation network", r"transit"]),
]

_ROAD_COMPILED = [(t, [re.compile(p, re.IGNORECASE) for p in ps]) for t, ps in _ROAD_TYPES]
_TOPIC_COMPILED = [(t, [re.compile(p, re.IGNORECASE) for p in ps]) for t, ps in _TOPIC_PATTERNS]

_SECTION_RE = re.compile(
    r"^(?:\d+(?:\.\d+)*\s+[A-Z]|[A-Z][A-Z\s\-/&]{4,}$)",
    re.MULTILINE,
)


def tag_road_types(text: str) -> list[str]:
    return [t for t, ps in _ROAD_COMPILED if any(p.search(text) for p in ps)]


def tag_topics(text: str) -> list[str]:
    return [t for t, ps in _TOPIC_COMPILED if any(p.search(text) for p in ps)]


def detect_section(text: str, previous: str) -> str:
    matches = _SECTION_RE.findall(text)
    if matches:
        return re.sub(r"\s+", " ", matches[-1].strip())
    return previous


def normalize(text: str) -> str:
    return re.sub(r"[ \t]+", " ", text.replace("\r\n", "\n").strip())


def split_paragraphs(text: str) -> list[str]:
    parts = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
    return parts or [text]


def chunk_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    text = normalize(text)
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


def extract_pages(pdf_path: Path) -> list[dict]:
    pages = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for i, page in enumerate(pdf.pages, start=1):
                pages.append({"page": i, "text": (page.extract_text() or "").strip()})
    except Exception as exc:
        print(f"  Warning: extraction error in {pdf_path.name}: {exc}")
    return pages


def parse_pdf_chunks(
    pdf_path: Path,
    doc_id: str,
    chunk_size: int = 1200,
    overlap: int = 200,
    min_chars: int = 80,
) -> list[dict]:
    pages = extract_pages(pdf_path)
    records: list[dict] = []
    current_section = ""

    for pg in pages:
        raw = normalize(pg["text"])
        current_section = detect_section(raw, current_section)
        for para in split_paragraphs(raw):
            if len(para) < min_chars:
                continue
            parts = [para] if len(para) <= chunk_size else chunk_text(para, chunk_size, overlap)
            for chunk in parts:
                if len(chunk) < min_chars:
                    continue
                records.append({
                    "doc_id": doc_id,
                    "section": current_section,
                    "page": pg["page"],
                    "road_types": tag_road_types(chunk),
                    "topics": tag_topics(chunk),
                    "chunk_text": chunk,
                })
    return records
