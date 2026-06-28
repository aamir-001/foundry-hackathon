"""Detect the wound-text format from the BODY content.

CLAUDE.md hard rule 5: never trust ``note_type`` -- a "Wound (SPN)" note was found
wrapping an Envive body. Detection is purely content-based.

Formats:
- envive               : signature line "*Envive Care Conference Review"
- spn_labeled          : SOAP / labeled block (Subjective:/Objective:, or explicit
                         Length:/Width:/Depth: labels)
- assessment_narrative : slash-delimited "Type to Loc / Measures X cm x X cm /
                         Stage: .. / Drainage: type, amount" (no Envive signature)
- prose                : shorthand in sentences ("Meas 4.2x3.1x1.5cm",
                         "measures aprx X x Xcm, depth Xcm")
"""

from __future__ import annotations

import re

from .text_fields import (
    FMT_ASSESSMENT_NARRATIVE,
    FMT_ENVIVE,
    FMT_PROSE,
    FMT_SPN_LABELED,
)

_ENVIVE_SIG = re.compile(r"\*?\s*envive\s+care\s+conference", re.IGNORECASE)
_SOAP_SIG = re.compile(r"\bsubjective\s*:", re.IGNORECASE)
_LABELED_SIG = re.compile(r"\b(length|width|depth)\s*:\s*\d", re.IGNORECASE)
# Slash-delimited templated narrative: "... / Measures ... / Stage:" or "/ Drainage:".
_NARRATIVE_SIG = re.compile(r"/\s*measures\b|measures\b.*/\s*stage", re.IGNORECASE)
_PROSE_SIG = re.compile(r"\bmeas\b|measures\s+aprx|\d+\.?\d*\s*x\s*\d", re.IGNORECASE)


def detect_format(text: str | None) -> str:
    """Return the detected source_format for a free-text wound body."""
    body = text or ""
    if _ENVIVE_SIG.search(body):
        return FMT_ENVIVE
    if _SOAP_SIG.search(body) or _LABELED_SIG.search(body):
        return FMT_SPN_LABELED
    if _NARRATIVE_SIG.search(body):
        return FMT_ASSESSMENT_NARRATIVE
    if _PROSE_SIG.search(body):
        return FMT_PROSE
    return FMT_PROSE  # safe default: best-effort prose parse
