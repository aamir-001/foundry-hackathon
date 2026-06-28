"""Shared wound-field extraction core.

Pure and testable: text blob (+ detected format) in -> ExtractionResult out.
No I/O, no network. The LLM fallback lives in ``llm.py`` and is the only side
effect in the extraction layer.

Confidence tiers (per CLAUDE.md / PRD revised):
- templated assessment_narrative / spn_labeled / assessment_structured with all
  four fields (L/W/D/drainage) parsed -> high
- prose shorthand -> medium
- envive, any LLM-filled result, or any incomplete extraction -> low
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict

# Source-format constants (detected from the BODY, never from note_type).
FMT_ASSESSMENT_NARRATIVE = "assessment_narrative"
FMT_ASSESSMENT_STRUCTURED = "assessment_structured"  # discrete sections Q/A (assessments only)
FMT_SPN_LABELED = "spn_labeled"                       # labeled / SOAP block
FMT_PROSE = "prose"
FMT_ENVIVE = "envive"
FMT_UNKNOWN = "unknown"

CONF_HIGH = "high"
CONF_MEDIUM = "medium"
CONF_LOW = "low"

WOUND_FIELDS = ("length_cm", "width_cm", "depth_cm", "drainage_amount")


@dataclass
class ExtractionResult:
    wound_type: str | None = None
    stage: str | None = None
    location: str | None = None
    length_cm: float | None = None
    width_cm: float | None = None
    depth_cm: float | None = None
    drainage_amount: str | None = None
    extraction_confidence: str = CONF_LOW
    source_format: str = FMT_UNKNOWN
    ambiguous: bool = False
    # True when an Anthropic API call produced/filled these fields.
    llm_used: bool = False
    # Non-persisted provenance: list of candidate wounds when multi-wound.
    candidates: list[dict] = field(default_factory=list)

    def is_complete(self) -> bool:
        """True when all four billable wound fields are present."""
        return all(getattr(self, f) is not None for f in WOUND_FIELDS)

    def has_any_measurement(self) -> bool:
        return any(
            getattr(self, f) is not None
            for f in ("length_cm", "width_cm", "depth_cm")
        )

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Normalization helpers (shared)
# ---------------------------------------------------------------------------
_WOUND_TYPE_PATTERNS: list[tuple[str, str]] = [
    (r"pressure\s+ulcer|pressure\s+injury|\bpu\b", "pressure_ulcer"),
    (r"diabetic|\bdfu\b|neuropathic", "diabetic_foot_ulcer"),
    (r"venous|venous\s+stasis|stasis", "venous_stasis_ulcer"),
    (r"arterial|ischemic", "arterial_ulcer"),
    (r"surgical|surgical\s+site|incision|\bssi\b", "surgical_site"),
    (r"abscess", "abscess"),
    (r"\bburn\b", "burn"),
]


def normalize_wound_type(text: str | None) -> str | None:
    if not text:
        return None
    low = text.lower()
    for pattern, canonical in _WOUND_TYPE_PATTERNS:
        if re.search(pattern, low):
            return canonical
    return None


_ROMAN = {"i": "1", "ii": "2", "iii": "3", "iv": "4"}


def normalize_stage(text: str | None) -> str | None:
    if not text:
        return None
    low = text.strip().lower()
    if low in ("n/a", "na", "none", "", "null", "-"):
        return None
    if "unstage" in low:
        return "unstageable"
    if "dti" in low or "deep tissue" in low:
        return "unstageable"
    # "stage 3", "stage iii", "stage three", or a bare digit/roman numeral.
    m = re.search(r"stage\s*([1-4ivx]+)", low)
    token = m.group(1) if m else low
    token = token.strip()
    if token in _ROMAN:
        return _ROMAN[token]
    if token in ("1", "2", "3", "4"):
        return token
    m2 = re.search(r"\b([1-4])\b", token)
    if m2:
        return m2.group(1)
    return None


def normalize_drainage(text: str | None) -> str | None:
    """Map free-text drainage descriptions onto none/light/moderate/heavy.

    Handles "scant", "serosanguineous, heavy", "moderate serous", "Mod serosang",
    "Min drainage", "slight serous", "no drainage", etc. The amount word wins;
    drainage *type* words (serous/serosanguineous/sanguineous/purulent) are ignored.
    """
    if not text:
        return None
    low = text.lower()
    if re.search(r"\bnone\b|no\s+drainage|\bdry\b|without\s+drainage", low):
        return "none"
    if re.search(r"heavy|copious|large|profuse", low):
        return "heavy"
    if re.search(r"moderate|\bmod\b", low):
        return "moderate"
    if re.search(r"light|scant|minimal|\bmin\b|slight|small|\blt\b", low):
        return "light"
    return None


_FLOAT = r"(\d+(?:\.\d+)?)"


def _to_float(s: str | None) -> float | None:
    if s is None:
        return None
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


# Location keywords -> kept as-is (title-cased) when found.
_LOCATION_RE = re.compile(
    r"(sacr\w*|coccyx|ischium|ischial|trochanter|hip|buttock|"
    r"heel|ankle|foot|plantar|toe|lower\s+leg|leg|calf|"
    r"abdom\w*|sternum|chest|cervical|thoracic|back|shoulder|elbow|"
    r"ear|scalp|head|knee|thigh|groin|perineum)",
    re.IGNORECASE,
)


def extract_location(text: str | None) -> str | None:
    if not text:
        return None
    # Prefer an explicit "to <Location>" or "<Laterality> <Location>" phrase.
    m = re.search(r"\bto\s+([A-Za-z][A-Za-z\s]*?)(?:\s*/|,|\.|$)", text)
    if m:
        loc = m.group(1).strip()
        if 0 < len(loc) <= 40:
            return loc
    m2 = _LOCATION_RE.search(text)
    if m2:
        # Include a leading laterality token if present right before it.
        start = m2.start()
        prefix = text[max(0, start - 8):start]
        lat = re.search(r"(left|right|bilateral|[LR])\s*$", prefix, re.IGNORECASE)
        loc = m2.group(1)
        return (f"{lat.group(1)} {loc}").strip() if lat else loc
    return None


# ---------------------------------------------------------------------------
# Measurement parsing
# ---------------------------------------------------------------------------
# 3-dim "x by x by x": 4.2x3.1x1.5cm  OR  4.3 cm x 1.8 cm x 0.3 cm
_MEAS_3D = re.compile(
    rf"{_FLOAT}\s*(?:cm)?\s*x\s*{_FLOAT}\s*(?:cm)?\s*x\s*{_FLOAT}\s*cm",
    re.IGNORECASE,
)
# 2-dim "x by x": 2.9 cm x 2.8 cm
_MEAS_2D = re.compile(
    rf"{_FLOAT}\s*(?:cm)?\s*x\s*{_FLOAT}\s*cm",
    re.IGNORECASE,
)
# Separate "depth 1.1cm" / "0.9cm deep"
_DEPTH = re.compile(rf"depth\s*{_FLOAT}\s*cm|{_FLOAT}\s*cm\s*deep", re.IGNORECASE)


def _parse_measurements(text: str) -> tuple[float | None, float | None, float | None]:
    """Return (length, width, depth) from the first measurement group in ``text``."""
    m3 = _MEAS_3D.search(text)
    if m3:
        return _to_float(m3.group(1)), _to_float(m3.group(2)), _to_float(m3.group(3))
    m2 = _MEAS_2D.search(text)
    if m2:
        length, width = _to_float(m2.group(1)), _to_float(m2.group(2))
        depth = None
        md = _DEPTH.search(text)
        if md:
            depth = _to_float(md.group(1) or md.group(2))
        return length, width, depth
    return None, None, None


# ---------------------------------------------------------------------------
# Per-format parsers
# ---------------------------------------------------------------------------
def _parse_narrative(text: str, source_format: str) -> ExtractionResult:
    """Slash-delimited 'Type to Location / Measures X cm x X cm / Stage: .. / Drainage: type, amount'."""
    res = ExtractionResult(source_format=source_format)
    res.wound_type = normalize_wound_type(text)
    res.location = extract_location(text)

    ms = re.search(r"stage\s*:\s*([^/\n]+)", text, re.IGNORECASE)
    res.stage = normalize_stage(ms.group(1) if ms else None)

    length, width, depth = _parse_measurements(text)
    res.length_cm, res.width_cm, res.depth_cm = length, width, depth

    md = re.search(r"drainage\s*:?\s*([^/\n]+)", text, re.IGNORECASE)
    res.drainage_amount = normalize_drainage(md.group(1) if md else text)
    return res


def _parse_spn_labeled(text: str) -> ExtractionResult:
    """SOAP / labeled block. 3-dim measurements + 'Drainage: <amount>' label."""
    res = ExtractionResult(source_format=FMT_SPN_LABELED)
    res.wound_type = normalize_wound_type(text)
    res.location = extract_location(text)

    # Explicit Length/Width/Depth labels (classic SPN), else x-by-x measurement.
    lab = {}
    for key in ("length", "width", "depth"):
        m = re.search(rf"{key}\s*:?\s*{_FLOAT}\s*cm", text, re.IGNORECASE)
        if m:
            lab[key] = _to_float(m.group(1))
    if lab:
        res.length_cm = lab.get("length")
        res.width_cm = lab.get("width")
        res.depth_cm = lab.get("depth")
    else:
        res.length_cm, res.width_cm, res.depth_cm = _parse_measurements(text)

    ms = re.search(r"stage\s*:?\s*([1-4ivx]+|unstageable|dti|deep tissue[^.\n]*)",
                   text, re.IGNORECASE)
    res.stage = normalize_stage(ms.group(1) if ms else None)

    md = re.search(r"drainage\s*:\s*([a-z]+)", text, re.IGNORECASE)
    if md:
        res.drainage_amount = normalize_drainage(md.group(1))
    else:
        res.drainage_amount = normalize_drainage(text)
    return res


# Multi-wound: a secondary wound introduced by "also eval - <loc> X x X, Xcm deep".
_SECOND_WOUND = re.compile(
    rf"also\s+eval\w*\s*[-:]?\s*(.*?){_FLOAT}\s*x\s*{_FLOAT}\s*,?\s*{_FLOAT}\s*cm\s*deep",
    re.IGNORECASE,
)


def _parse_prose(text: str) -> ExtractionResult:
    """Shorthand prose. May describe two wounds; select the primary by area."""
    primary = ExtractionResult(source_format=FMT_PROSE)
    primary.wound_type = normalize_wound_type(text)
    primary.location = extract_location(text)
    primary.length_cm, primary.width_cm, primary.depth_cm = _parse_measurements(text)
    primary.drainage_amount = normalize_drainage(text)

    ms = re.search(r"stage\s*:?\s*([1-4ivx]+|unstageable|dti)", text, re.IGNORECASE)
    primary.stage = normalize_stage(ms.group(1) if ms else None)

    # Detect a second wound and pick the clinically primary one (largest area;
    # stage tie-break first if both staged).
    sec = _SECOND_WOUND.search(text)
    if sec:
        sl, sw, sd = _to_float(sec.group(2)), _to_float(sec.group(3)), _to_float(sec.group(4))
        cand_a = {
            "length_cm": primary.length_cm, "width_cm": primary.width_cm,
            "depth_cm": primary.depth_cm, "stage": primary.stage,
            "source": "primary_clause",
        }
        cand_b = {
            "length_cm": sl, "width_cm": sw, "depth_cm": sd, "stage": None,
            "source": "also_eval_clause",
        }
        primary.candidates = [cand_a, cand_b]
        chosen, ambiguous = _select_primary(cand_a, cand_b)
        primary.length_cm = chosen["length_cm"]
        primary.width_cm = chosen["width_cm"]
        primary.depth_cm = chosen["depth_cm"]
        primary.ambiguous = ambiguous
    return primary


def _area(c: dict) -> float | None:
    if c.get("length_cm") is not None and c.get("width_cm") is not None:
        return c["length_cm"] * c["width_cm"]
    return None


def _select_primary(a: dict, b: dict) -> tuple[dict, bool]:
    """Pick the clinically primary wound: highest stage, else largest area.

    Returns (chosen, ambiguous). Ambiguous when neither stage nor area can
    separate them.
    """
    sa, sb = a.get("stage"), b.get("stage")
    if sa and sb and sa != sb:
        return (a, False) if sa > sb else (b, False)
    area_a, area_b = _area(a), _area(b)
    if area_a is not None and area_b is not None:
        if area_a == area_b:
            return a, True  # same size, can't separate
        return (a, False) if area_a > area_b else (b, False)
    # One or both areas unknown -> can't confidently choose.
    return a, True


# ---------------------------------------------------------------------------
# Confidence assignment
# ---------------------------------------------------------------------------
def assign_confidence(res: ExtractionResult, llm_used: bool = False) -> str:
    if llm_used or res.source_format == FMT_ENVIVE:
        return CONF_LOW
    if not res.is_complete():
        return CONF_LOW
    if res.source_format in (
        FMT_ASSESSMENT_NARRATIVE, FMT_ASSESSMENT_STRUCTURED, FMT_SPN_LABELED
    ):
        return CONF_HIGH
    if res.source_format == FMT_PROSE:
        return CONF_MEDIUM
    return CONF_LOW


# ---------------------------------------------------------------------------
# Public entry point: text + format -> ExtractionResult (regex tiers only)
# ---------------------------------------------------------------------------
def extract_fields(text: str, source_format: str) -> ExtractionResult:
    """Regex-based extraction for non-LLM formats. Envive returns an empty result
    flagged for the LLM fallback (handled by the adapters)."""
    text = text or ""
    if source_format == FMT_SPN_LABELED:
        res = _parse_spn_labeled(text)
    elif source_format in (FMT_ASSESSMENT_NARRATIVE,):
        res = _parse_narrative(text, source_format)
    elif source_format == FMT_PROSE:
        res = _parse_prose(text)
    elif source_format == FMT_ENVIVE:
        # Envive routes to the LLM fallback; return a shell so callers can decide.
        res = ExtractionResult(source_format=FMT_ENVIVE)
    else:
        # Unknown: best-effort prose parse.
        res = _parse_prose(text)
        res.source_format = FMT_UNKNOWN

    res.extraction_confidence = assign_confidence(res)
    return res
