"""Anthropic LLM fallback for wound extraction.

Called ONLY when the body is Envive, or when the regex tiers returned an
incomplete/low-confidence result -- never on everything (CLAUDE.md). The LLM is
the only side effect in the extraction layer.

Contract:
- Bounded prompt: JSON only, fixed keys, null for absent fields.
- Parse defensively (strip code fences, try/except). Bad output -> low confidence,
  never crash.
- Degrades gracefully when ANTHROPIC_API_KEY is missing or the call fails: keeps
  the regex result if one was provided, otherwise returns a low-confidence shell.
"""

from __future__ import annotations

import json
import logging
import re

from .. import config
from .text_fields import (
    CONF_LOW,
    FMT_ENVIVE,
    ExtractionResult,
    normalize_drainage,
    normalize_stage,
    normalize_wound_type,
    _to_float,
)

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 400

_PROMPT = """You are a clinical wound-care data extractor. Extract ONLY the wound \
fields from the note below. Return STRICT JSON and nothing else -- no prose, no \
code fences.

Keys (use null when a field is not stated in the text):
  "wound_type": one of pressure_ulcer, diabetic_foot_ulcer, venous_stasis_ulcer, \
arterial_ulcer, surgical_site, abscess, burn, or null
  "stage": "1","2","3","4","unstageable", or null (only for pressure ulcers)
  "location": short string or null
  "length_cm": number or null
  "width_cm": number or null
  "depth_cm": number or null
  "drainage_amount": one of none, light, moderate, heavy, or null

If two wounds are described, extract the clinically primary one (highest stage, \
else largest length x width).

NOTE:
\"\"\"
{note}
\"\"\"

JSON:"""


def _client():
    """Return an Anthropic client, or None when the key is unavailable."""
    if not config.ANTHROPIC_API_KEY:
        return None
    try:
        import anthropic
        return anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Anthropic client init failed: %s", exc)
        return None


def _parse_json(raw: str) -> dict | None:
    """Defensively parse model output into a dict (strip code fences)."""
    if not raw:
        return None
    cleaned = raw.strip()
    cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
    cleaned = re.sub(r"```$", "", cleaned).strip()
    # Grab the first {...} block if there's surrounding text.
    m = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if m:
        cleaned = m.group(0)
    try:
        obj = json.loads(cleaned)
        return obj if isinstance(obj, dict) else None
    except (TypeError, ValueError):
        return None


def extract_with_llm(
    text: str,
    source_format: str,
    regex_result: ExtractionResult | None = None,
) -> ExtractionResult:
    """Extract wound fields via the LLM. Always returns an ExtractionResult.

    On any failure, falls back to ``regex_result`` (if given) or a low-confidence
    shell. The returned result keeps the original ``source_format`` so the report
    still shows envive/prose/etc., and sets ``llm_used`` / ``extraction_confidence``
    appropriately.
    """
    client = _client()
    if client is None:
        return _fallback(regex_result, source_format, reason="no_api_key")

    try:
        msg = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            messages=[{"role": "user", "content": _PROMPT.format(note=text)}],
        )
        raw = "".join(
            block.text for block in msg.content if getattr(block, "type", None) == "text"
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Anthropic call failed (%s): %s", source_format, exc)
        return _fallback(regex_result, source_format, reason="api_error")

    data = _parse_json(raw)
    if data is None:
        logger.warning("Anthropic returned unparseable output (%s)", source_format)
        return _fallback(regex_result, source_format, reason="bad_output")

    res = ExtractionResult(source_format=source_format, llm_used=True)
    res.wound_type = normalize_wound_type(data.get("wound_type")) or data.get("wound_type")
    res.stage = normalize_stage(str(data["stage"])) if data.get("stage") is not None else None
    res.location = data.get("location")
    res.length_cm = _to_float(_num(data.get("length_cm")))
    res.width_cm = _to_float(_num(data.get("width_cm")))
    res.depth_cm = _to_float(_num(data.get("depth_cm")))
    res.drainage_amount = normalize_drainage(data.get("drainage_amount")) or \
        _passthrough_drainage(data.get("drainage_amount"))
    # LLM-filled results are always low confidence per the tiers.
    res.extraction_confidence = CONF_LOW
    if not res.is_complete():
        res.ambiguous = True
    return res


def _num(v) -> str | None:
    if v is None:
        return None
    return str(v)


def _passthrough_drainage(v) -> str | None:
    if isinstance(v, str) and v.lower() in ("none", "light", "moderate", "heavy"):
        return v.lower()
    return None


def _fallback(
    regex_result: ExtractionResult | None, source_format: str, reason: str
) -> ExtractionResult:
    if regex_result is not None:
        # Keep best-effort regex fields; do not claim the LLM ran.
        regex_result.ambiguous = regex_result.ambiguous or (not regex_result.is_complete())
        return regex_result
    shell = ExtractionResult(source_format=source_format or FMT_ENVIVE)
    shell.extraction_confidence = CONF_LOW
    shell.ambiguous = True
    return shell
