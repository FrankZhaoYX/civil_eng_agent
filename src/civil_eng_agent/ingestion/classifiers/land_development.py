"""doc_type heuristics for Land Development documents."""
from __future__ import annotations

import re


_DRAWING_RE = re.compile(r"\b(DS|NHF)-\d+", re.IGNORECASE)
_SPEC_RE = re.compile(r"specification", re.IGNORECASE)
_BID_RE = re.compile(r"bid[\s_-]form", re.IGNORECASE)
_MASTER_RE = re.compile(r"master[\s_-]plan|streetscape[\s_-]master", re.IGNORECASE)


def classify(filename: str) -> str:
    stem = filename.lower()
    if _DRAWING_RE.search(stem):
        return "standard_drawing"
    if _SPEC_RE.search(stem):
        return "specification"
    if _BID_RE.search(stem):
        return "bid_form"
    if _MASTER_RE.search(stem):
        return "master_plan"
    return "guideline"
