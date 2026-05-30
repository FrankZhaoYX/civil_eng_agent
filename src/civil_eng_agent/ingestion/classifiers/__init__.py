from __future__ import annotations

import importlib
import re


def get_classifier(category: str, subcategory: str):
    """Return a classify(filename) -> doc_type function for the given category."""
    slug = re.sub(r"[^a-z0-9]+", "_", category.lower()).strip("_")
    try:
        mod = importlib.import_module(f"civil_eng_agent.ingestion.classifiers.{slug}")
        return mod.classify
    except ModuleNotFoundError:
        return _default_classify


def _default_classify(filename: str) -> str:
    return "guideline"
