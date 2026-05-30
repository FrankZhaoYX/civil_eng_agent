"""Unit tests for search and ingestion logic."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from civil_eng_agent.config import Config, EmbedConfig
from civil_eng_agent.ingestion.classifiers import get_classifier
from civil_eng_agent.ingestion.classifiers.land_development import classify
from civil_eng_agent.ingestion.parse_pdf import tag_road_types, tag_topics
from civil_eng_agent.store.repository import Repository


# ---------------------------------------------------------------------------
# Classifier tests
# ---------------------------------------------------------------------------

def test_classify_guideline():
    assert classify("designing-great-streets-guidelines-part-1.pdf") == "guideline"


def test_classify_standard_drawing():
    assert classify("DS-100-intersection-details.pdf") == "standard_drawing"


def test_classify_specification():
    assert classify("roadworks-specifications.docx") == "specification"


def test_classify_bid_form():
    assert classify("bid-form-2024.docx") == "bid_form"


def test_get_classifier_land_development():
    fn = get_classifier("Land Development", "Construction Design Guidelines and Standards")
    assert callable(fn)
    assert fn("DS-200.pdf") == "standard_drawing"


# ---------------------------------------------------------------------------
# Tagging tests
# ---------------------------------------------------------------------------

def test_tag_road_types_avenue():
    tags = tag_road_types("The Avenue shall have travel lanes of 3.3 m.")
    assert "avenue" in tags


def test_tag_road_types_connector():
    tags = tag_road_types("On a Connector, the design speed is 60 km/h.")
    assert "connector" in tags


def test_tag_topics_cross_section():
    tags = tag_topics("The cross-section for this road includes a boulevard width of 4.5 m.")
    assert "cross_section" in tags


def test_tag_topics_cycling():
    tags = tag_topics("A cycle track shall be provided on this segment.")
    assert "cycling" in tags


# ---------------------------------------------------------------------------
# Repository tests
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_repo(tmp_path: Path) -> Repository:
    db = tmp_path / "test.db"
    return Repository(db)


def test_upsert_and_list_document(tmp_repo: Repository):
    from datetime import datetime, timezone
    tmp_repo.upsert_document({
        "doc_id": "test-doc",
        "category": "Land Development",
        "subcategory": "Construction Design Guidelines and Standards",
        "title": "Test Document",
        "doc_type": "guideline",
        "source_url": "https://example.com",
        "filename": "test.pdf",
        "format": "pdf",
        "version_date": "2024-01-01",
        "sha256": "abc123",
        "ingested_at": datetime.now(timezone.utc).isoformat(),
        "is_latest": 1,
    })
    docs = tmp_repo.list_documents()
    assert len(docs) == 1
    assert docs[0]["doc_id"] == "test-doc"


def test_insert_and_fts_chunks(tmp_repo: Repository):
    from datetime import datetime, timezone
    tmp_repo.upsert_document({
        "doc_id": "search-doc",
        "category": "Land Development",
        "subcategory": "Construction Design Guidelines and Standards",
        "title": "Search Doc",
        "doc_type": "guideline",
        "source_url": "https://example.com",
        "filename": "search.pdf",
        "format": "pdf",
        "version_date": "2024-01-01",
        "sha256": "def456",
        "ingested_at": datetime.now(timezone.utc).isoformat(),
        "is_latest": 1,
    })
    chunks = [
        {
            "doc_id": "search-doc",
            "section": "4.2",
            "page": 47,
            "road_types": ["avenue"],
            "topics": ["cross_section"],
            "chunk_text": "The minimum travel lane width on an Avenue is 3.3 m.",
        }
    ]
    tmp_repo.insert_chunks(chunks)
    results = tmp_repo.fts_search("travel lane width avenue", limit=5)
    assert len(results) > 0
    assert "3.3" in results[0]["chunk_text"]


def test_stats(tmp_repo: Repository):
    stats = tmp_repo.stats()
    assert "documents" in stats
    assert "chunks" in stats
    assert isinstance(stats["documents"], int)
