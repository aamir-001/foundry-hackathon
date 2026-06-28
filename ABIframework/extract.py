import re
import json
import logging

log = logging.getLogger(__name__)

DRAINAGE_MAP = {
    "none": "none", "no drainage": "none", "dry": "none",
    "scant": "light", "minimal": "light", "small": "light", "light": "light",
    "moderate": "moderate", "mod": "moderate",
    "large": "heavy", "heavy": "heavy", "copious": "heavy", "profuse": "heavy",
}

def _normalise_drainage(raw):
    if not raw:
        return None
    raw = raw.lower()
    for key, val in DRAINAGE_MAP.items():
        if key in raw:
            return val
    return None

MEASUREMENT_PATTERNS = [
    # "Length: 3.2 cm  Width: 2.1 cm  Depth: 0.4 cm"
    r"[Ll]ength\s*[:\-]?\s*([0-9]+\.?[0-9]*)\s*cm.*?[Ww]idth\s*[:\-]?\s*([0-9]+\.?[0-9]*)\s*cm.*?[Dd]epth\s*[:\-]?\s*([0-9]+\.?[0-9]*)\s*cm",
    # "Meas 4.2x3.1x1.5cm"
    r"[Mm]eas(?:ures?)?\s*[:\-]?\s*([0-9]+\.?[0-9]*)\s*[xX]\s*([0-9]+\.?[0-9]*)\s*[xX]\s*([0-9]+\.?[0-9]*)\s*cm",
    # "3.2 x 2.1 x 0.4 cm"
    r"([0-9]+\.?[0-9]*)\s*[xX]\s*([0-9]+\.?[0-9]*)\s*[xX]\s*([0-9]+\.?[0-9]*)\s*cm",
    # "3.1 cm x 3.4 cm" (2D only — common in Envive/assessment answers)
    r"([0-9]+\.?[0-9]*)\s*cm\s*[xX]\s*([0-9]+\.?[0-9]*)\s*cm",
    # "Measures 3.1 cm x 3.4 cm"
    r"[Mm]easures?\s+([0-9]+\.?[0-9]*)\s*cm\s*[xX]\s*([0-9]+\.?[0-9]*)\s*cm",
]

def _extract_measurements(text):
    # Try 3D patterns first
    for pat in MEASUREMENT_PATTERNS[:3]:
        m = re.search(pat, text, re.IGNORECASE | re.DOTALL)
        if m:
            return {"length_cm": float(m.group(1)),
                    "width_cm":  float(m.group(2)),
                    "depth_cm":  float(m.group(3))}
    # Try 2D patterns (no depth)
    for pat in MEASUREMENT_PATTERNS[3:]:
        m = re.search(pat, text, re.IGNORECASE | re.DOTALL)
        if m:
            return {"length_cm": float(m.group(1)),
                    "width_cm":  float(m.group(2)),
                    "depth_cm":  None}
    return {"length_cm": None, "width_cm": None, "depth_cm": None}

WOUND_TYPES = [
    (r"pressure\s+ulcer|pressure\s+sore|decubitus",          "pressure_ulcer"),
    (r"diabetic\s+foot\s+ulcer|DFU|neuropathic\s+ulcer",     "diabetic_foot_ulcer"),
    (r"venous\s+(stasis\s+)?ulcer|VSU|venous\s+leg\s+ulcer|venous\s+to", "venous_stasis_ulcer"),
    (r"arterial\s+ulcer|ischemic\s+ulcer",                   "arterial_ulcer"),
    (r"surgical\s+site\s+infection|SSI|post.{0,5}op\s+wound","surgical_site_infection"),
    (r"\babscess\b",                                          "abscess"),
    (r"\bburn\b",                                             "burn"),
]

STAGES = [
    (r"[Ss]tage\s*(IV|4)\b", 4),
    (r"[Ss]tage\s*(III|3)\b", 3),
    (r"[Ss]tage\s*(II|2)\b", 2),
    (r"[Ss]tage\s*(I\b|1\b)", 1),
    (r"[Uu]nstageable|[Dd]eep\s+[Tt]issue", "unstageable"),
]

def _extract_from_text(text):
    if not text:
        return {}
    wound_type = None
    for pat, wtype in WOUND_TYPES:
        if re.search(pat, text, re.IGNORECASE):
            wound_type = wtype
            break
    stage = None
    if wound_type == "pressure_ulcer":
        for pat, s in STAGES:
            if re.search(pat, text):
                stage = s
                break
    location = None
    loc_m = re.search(r"[Ll]ocation\s*[:\-]\s*([^\n,\.\/]{3,50})", text)
    if loc_m:
        location = loc_m.group(1).strip()
    # Also try "Venous to [location]" pattern
    if not location:
        loc_m2 = re.search(r"(?:venous|wound)\s+(?:to|at|on)\s+([^\n,\.\/]{3,40})", text, re.IGNORECASE)
        if loc_m2:
            location = loc_m2.group(1).strip()
    drainage = None
    drain_m = re.search(r"[Dd]rainage\s*[:\-]?\s*([^\n,\.\/]{2,40})", text)
    if drain_m:
        drainage = _normalise_drainage(drain_m.group(1))
    if not drainage:
        drainage = _normalise_drainage(text)
    return {"wound_type": wound_type, "stage": stage, "location": location,
            "drainage": drainage, **_extract_measurements(text)}

def _parse_assessment_raw_json(raw):
    """
    Handles both assessment formats:
    1. Flat: {"wound_type": "pressure_ulcer", "length_cm": 3.2, ...}
    2. Nested: {"sections": [{"questions": [{"answer": "Venous to..."}]}]}
    """
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        return {}

    # Format 1: flat keys
    if data.get('wound_type') or data.get('length_cm'):
        return {
            "wound_type": data.get("wound_type"),
            "stage":      data.get("stage"),
            "location":   data.get("location"),
            "length_cm":  data.get("length_cm"),
            "width_cm":   data.get("width_cm"),
            "depth_cm":   data.get("depth_cm"),
            "drainage":   _normalise_drainage(data.get("drainage_amount")),
            "assessment_date": data.get("assessmentDate", ""),
        }

    # Format 2: nested sections/questions
    text = ""
    for section in data.get('sections', []):
        for q in section.get('questions', []):
            answer = q.get('answer', '')
            if answer:
                text += answer + "\n"

    if not text:
        return {}

    fields = _extract_from_text(text)
    fields['assessment_date'] = data.get('assessmentDate', '')
    return fields

def _detect_format(text, note_type):
    if note_type and "SPN" in str(note_type):
        if re.search(r"[Ll]ength\s*[:\-]", text):
            return "SOAP"
    if re.search(r"[Mm]eas\s*[:\-]?\s*[0-9]", text):
        return "Prose"
    if re.search(r"[Ww]ound\s*[#\-]?\s*2|[Ss]econdary\s+[Ww]ound", text):
        return "Multi-wound"
    return "Envive"

def _extract_with_llm(note_text, task="extract"):
    try:
        import anthropic
        client = anthropic.Anthropic()
        if task == "extract":
            prompt = f"""You are a clinical data extractor for wound care billing.
Extract ONLY these fields. Return valid JSON only, no explanation.
Keys: wound_type, stage, location, length_cm, width_cm, depth_cm, drainage_amount
Use null for missing fields.
wound_type options: pressure_ulcer, diabetic_foot_ulcer, venous_stasis_ulcer, arterial_ulcer, surgical_site_infection, abscess, burn, or null.
drainage_amount options: none, light, moderate, heavy, or null.
Note: {note_text[:2000]}"""
        else:
            prompt = f"""This note describes multiple wounds. Return ONLY the text
describing the primary wound (most severe or largest). Note: {note_text[:2000]}"""
        resp = client.messages.create(
            model="claude-sonnet-4-6", max_tokens=500,
            messages=[{"role": "user", "content": prompt}])
        raw = resp.content[0].text.strip()
        if task == "extract":
            data = json.loads(raw.replace("```json", "").replace("```", "").strip())
            return {"wound_type": data.get("wound_type"), "stage": data.get("stage"),
                    "location": data.get("location"),
                    "drainage": _normalise_drainage(data.get("drainage_amount")),
                    "length_cm": data.get("length_cm"),
                    "width_cm":  data.get("width_cm"),
                    "depth_cm":  data.get("depth_cm")}
        return {"primary_section": raw}
    except Exception as exc:
        log.warning(f"LLM extraction failed: {exc}")
        return {}

def extract_wound_data(patient):
    result = {"wound_type": None, "stage": None, "location": None,
              "length_cm": None, "width_cm": None, "depth_cm": None,
              "drainage": None, "source": None, "note_format": None, "confidence": "low"}

    # 1. Structured assessments — now handles nested format
    for a in sorted(patient.get("assessments", []),
                    key=lambda x: x.get("assessment_date", ""), reverse=True):
        raw = a.get("raw_json")
        if not raw:
            continue
        fields = _parse_assessment_raw_json(raw)
        if not fields.get("wound_type"):
            continue
        l, w, d = fields.get("length_cm"), fields.get("width_cm"), fields.get("depth_cm")
        result.update({
            "wound_type": fields.get("wound_type"),
            "stage":      fields.get("stage"),
            "location":   fields.get("location"),
            "length_cm":  l, "width_cm": w, "depth_cm": d,
            "drainage":   fields.get("drainage"),
            "source":     "assessment",
            "note_format":"structured",
            "confidence": "high" if all([l, w]) else "medium",
        })
        return result

    # 2. Progress notes
    for note in sorted(patient.get("notes", []),
                       key=lambda n: n.get("effective_date", ""), reverse=True):
        text = note.get("note_text", "") or ""
        note_type = note.get("note_type", "") or ""
        if not text.strip():
            continue
        fmt = _detect_format(text, note_type)
        if fmt == "Multi-wound":
            pick = _extract_with_llm(text, task="primary")
            parse_text = pick.get("primary_section", text)
        else:
            parse_text = text
        fields = _extract_from_text(parse_text)
        if not fields.get("wound_type"):
            if fmt == "Envive":
                llm_fields = _extract_with_llm(text, task="extract")
                if llm_fields.get("wound_type"):
                    result.update({**llm_fields, "source": "llm",
                                   "note_format": "Envive", "confidence": "medium"})
                    return result
            continue
        has_all = all(fields.get(k) for k in ["length_cm", "width_cm"])
        has_drn = bool(fields.get("drainage"))
        if has_all and has_drn:
            confidence = "high" if fmt in ("SOAP", "structured") else "medium"
        elif has_all or has_drn:
            confidence = "medium"
        else:
            confidence = "low"
        result.update({**fields, "source": "note",
                       "note_format": fmt, "confidence": confidence})
        return result
    return result

def compute_wound_trajectory(patient):
    points = []
    for a in patient.get("assessments", []):
        raw = a.get("raw_json")
        if not raw:
            continue
        try:
            fields = _parse_assessment_raw_json(raw)
            l, w  = fields.get("length_cm"), fields.get("width_cm")
            date  = fields.get("assessment_date") or a.get("assessment_date", "")
            if l and w and date:
                points.append({"date": str(date), "area": round(float(l) * float(w), 2)})
        except Exception:
            continue
    points = sorted(points, key=lambda x: x["date"])
    visit_count = len(points)
    if visit_count < 2:
        return {"visit_count": visit_count, "wound_trend": "insufficient_data",
                "area_change_pct": None, "compliance_flag": False,
                "measurement_jump_flag": False, "high_frequency_flag": False}
    first_area = points[0]["area"]
    last_area  = points[-1]["area"]
    delta_pct  = round((last_area - first_area) / first_area * 100, 1) if first_area else None
    if delta_pct is None:           trend = "insufficient_data"
    elif delta_pct <= -10:          trend = "improving"
    elif delta_pct >= 10:           trend = "worsening"
    else:                           trend = "stalled"
    compliance_flag = visit_count >= 3 and trend in ("stalled", "worsening")
    measurement_jump_flag = any(
        points[i+1]["area"] > points[i]["area"] * 1.5
        for i in range(len(points) - 1))
    high_frequency_flag = False
    if visit_count >= 4:
        try:
            from datetime import datetime
            dates = [datetime.fromisoformat(str(p["date"])) for p in points]
            span  = (dates[-1] - dates[0]).days
            high_frequency_flag = span <= 30
        except Exception:
            pass
    return {"visit_count": visit_count, "wound_trend": trend,
            "area_change_pct": delta_pct, "compliance_flag": compliance_flag,
            "measurement_jump_flag": measurement_jump_flag,
            "high_frequency_flag": high_frequency_flag}
