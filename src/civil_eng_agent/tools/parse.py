"""parse_design_pdf tool: extract design parameters from a local PDF."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from civil_eng_agent.config import Config


class ExtractedDesign(BaseModel):
    file_path: str
    parameters: dict[str, Any]
    confidence: dict[str, float]
    needs_confirmation: list[str]


# Patterns for common numeric parameters in design PDFs
_PATTERNS: list[tuple[str, str, str]] = [
    # (param_name, regex_pattern, unit)
    ("travel_lane_width_m", r"travel[\s\-]+lane[s]?[\s\-:]+(\d+\.?\d*)\s*m", "m"),
    ("shoulder_width_m", r"shoulder[\s\-:]+(\d+\.?\d*)\s*m", "m"),
    ("boulevard_width_m", r"boulevard[\s\-:]+(\d+\.?\d*)\s*m", "m"),
    ("sidewalk_width_m", r"sidewalk[\s\-:]+(\d+\.?\d*)\s*m", "m"),
    ("design_speed_kmh", r"design[\s\-]+speed[\s\-:]+(\d+)\s*km/?h", "km/h"),
    ("right_of_way_m", r"right[\s\-]+of[\s\-]+way[\s\-:]+(\d+\.?\d*)\s*m", "m"),
    ("turning_radius_m", r"turning[\s\-]+radius[\s\-:]+(\d+\.?\d*)\s*m", "m"),
    ("road_type", r"(avenue|connector|main street|city[\s\-]centre street|rural road)", ""),
]
_COMPILED = [(n, re.compile(pat, re.IGNORECASE), unit) for n, pat, unit in _PATTERNS]

_HIGH_CONFIDENCE = 0.9
_LOW_CONFIDENCE = 0.5


def parse_design_pdf(
    file_path: str,
    use_vision: bool = False,
    cfg: Config | None = None,
) -> ExtractedDesign:
    """Parse a local design PDF and extract recognisable parameters.

    use_vision=True invokes Claude Vision for figure-heavy PDFs (off by default;
    requires ANTHROPIC_API_KEY and explicit opt-in).
    """
    if cfg is None:
        cfg = Config.load()

    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Design PDF not found: {file_path}")
    if cfg.air_gapped and use_vision:
        raise ValueError("use_vision is disabled in air-gapped mode.")

    from civil_eng_agent.ingestion.parse_pdf import extract_pages

    pages = extract_pages(path)
    full_text = "\n".join(pg["text"] for pg in pages)

    parameters: dict[str, Any] = {}
    confidence: dict[str, float] = {}

    for param_name, pattern, unit in _COMPILED:
        match = pattern.search(full_text)
        if match:
            raw = match.group(1)
            try:
                val = float(raw) if "." in raw else int(raw)
            except ValueError:
                val = raw
            parameters[param_name] = val
            confidence[param_name] = _HIGH_CONFIDENCE

    if use_vision and cfg.anthropic_api_key:
        _vision_augment(path, parameters, confidence, cfg)

    needs_confirmation = [
        k for k, v in confidence.items() if v < _HIGH_CONFIDENCE
    ] + _missing_required(parameters)

    return ExtractedDesign(
        file_path=file_path,
        parameters=parameters,
        confidence=confidence,
        needs_confirmation=list(dict.fromkeys(needs_confirmation)),
    )


def _missing_required(params: dict) -> list[str]:
    required = ["road_type", "travel_lane_width_m", "design_speed_kmh"]
    return [r for r in required if r not in params]


def _vision_augment(
    path: Path,
    parameters: dict,
    confidence: dict,
    cfg: Config,
) -> None:
    """Use Claude Vision to extract parameters from plan-sheet figures."""
    import base64

    import anthropic
    try:
        from pdf2image import convert_from_path  # type: ignore
    except ImportError:
        return

    client = anthropic.Anthropic(api_key=cfg.anthropic_api_key)
    images = convert_from_path(str(path), first_page=1, last_page=3, dpi=150)

    for img in images:
        import io
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        b64 = base64.b64encode(buf.getvalue()).decode()

        msg = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}},
                    {"type": "text", "text": (
                        "This is a plan sheet from a York Region road design submission. "
                        "Extract any numeric design parameters (lane widths, speeds, etc.) "
                        "you can read from the drawing. Return JSON: {param: value}."
                    )},
                ],
            }],
        )
        import json
        raw = msg.content[0].text
        try:
            start = raw.find("{")
            end = raw.rfind("}") + 1
            extracted = json.loads(raw[start:end]) if start >= 0 else {}
            for k, v in extracted.items():
                if k not in parameters:
                    parameters[k] = v
                    confidence[k] = _LOW_CONFIDENCE
        except (json.JSONDecodeError, ValueError):
            pass
