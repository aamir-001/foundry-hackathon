"""Adapter: an assessment's ``raw_json`` -> ExtractionResult.

Phase-2 data finding: assessment ``raw_json`` comes in TWO shapes (the spec
anticipated only the first):

1. Narrative shape -- a single WOUND_INFO section with one "Wound narrative"
   answer holding a slash-delimited string:
     "Pressure Ulcer to Right hip / Measures 2.9 cm x 2.8 cm / Stage: Stage 3 /
      Drainage: serosanguineous, heavy"
   -> dig the narrative out, run the shared regex core (assessment_narrative).

2. Structured shape -- discrete sections (LOCATION / WOUND / DRAINAGE / WOUND_BED)
   with one field per question ("Wound Type", "Stage", "Length (cm)", "Width (cm)",
   "Depth (cm)", "Drainage Amount", "Location"). This is the gold source (has depth)
   -> read the fields directly (assessment_structured, high confidence).

raw_json may arrive as a dict (jsonb) or a JSON string; both are handled.
"""

from __future__ import annotations

import json
from typing import Any

from .text_fields import (
    FMT_ASSESSMENT_NARRATIVE,
    FMT_ASSESSMENT_STRUCTURED,
    ExtractionResult,
    assign_confidence,
    extract_fields,
    normalize_drainage,
    normalize_stage,
    normalize_wound_type,
    _to_float,
)


def _as_obj(raw_json: Any) -> dict:
    if raw_json is None:
        return {}
    if isinstance(raw_json, dict):
        return raw_json
    if isinstance(raw_json, str):
        try:
            return json.loads(raw_json)
        except (TypeError, ValueError):
            return {}
    return {}


def _walk_qa(obj: dict) -> dict[str, str]:
    """Flatten sections -> questions into a {question: answer} map."""
    qa: dict[str, str] = {}
    for section in obj.get("sections", []) or []:
        for q in section.get("questions", []) or []:
            question = (q.get("question") or "").strip()
            answer = q.get("answer")
            if question:
                qa[question] = answer
    return qa


def _find_narrative(qa: dict[str, str]) -> str | None:
    for question, answer in qa.items():
        if "narrative" in question.lower() and isinstance(answer, str):
            return answer
    return None


def extract_from_assessment(raw_json: Any) -> ExtractionResult:
    obj = _as_obj(raw_json)
    qa = _walk_qa(obj)

    narrative = _find_narrative(qa)
    if narrative:
        # Shape 1: slash-delimited narrative -> shared regex core.
        return extract_fields(narrative, FMT_ASSESSMENT_NARRATIVE)

    # Shape 2: structured discrete fields -> read directly.
    res = ExtractionResult(source_format=FMT_ASSESSMENT_STRUCTURED)

    def _get(*names: str) -> str | None:
        for n in names:
            for question, answer in qa.items():
                if question.strip().lower() == n.lower():
                    return answer
        return None

    res.wound_type = normalize_wound_type(_get("Wound Type"))
    res.stage = normalize_stage(_get("Stage"))
    res.length_cm = _to_float(_get("Length (cm)", "Length"))
    res.width_cm = _to_float(_get("Width (cm)", "Width"))
    res.depth_cm = _to_float(_get("Depth (cm)", "Depth"))

    # Drainage amount: prefer the explicit amount, else derive from type/present.
    amount = _get("Drainage Amount") or _get("Drainage")
    res.drainage_amount = normalize_drainage(amount)

    location = _get("Location")
    laterality = _get("Laterality")
    if location:
        # Prepend laterality only when it adds information (not "bilateral" and not
        # already present in the location string, e.g. "Left" + "Left buttock").
        if laterality and laterality.lower() != "bilateral" \
                and laterality.lower() not in location.lower():
            res.location = f"{laterality} {location}".strip()
        else:
            res.location = location

    res.extraction_confidence = assign_confidence(res)
    return res
