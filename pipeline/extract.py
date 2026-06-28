import re
import json
import os
from pipeline.database import get_connection, upsert_wound_extraction

LLM_ENABLED = os.environ.get("LLM_ENABLED", "false").lower() == "true"

try:
    import anthropic
    CLAUDE_AVAILABLE = True
except ImportError:
    CLAUDE_AVAILABLE = False

CLAUDE_MODEL = "claude-haiku-4-5-20251001"

WOUND_TYPE_PATTERNS = [
    (r"pressure\s*(ulcer|injury|sore)", "pressure_ulcer"),
    (r"diabetic\s*(foot\s*)?(ulcer|wound)?", "diabetic_foot_ulcer"),
    (r"venous\s*(stasis\s*)?(ulcer|wound)?", "venous_stasis_ulcer"),
    (r"arterial\s*(ulcer|wound)", "arterial_ulcer"),
    (r"surgical\s*site\s*(infection|wound)", "surgical_site_infection"),
    (r"abscess", "abscess"),
    (r"burn", "burn"),
    (r"(decubitus|bedsore)", "pressure_ulcer"),
    (r"wound\s*type[:\s]*(pressure)", "pressure_ulcer"),
]

STAGE_PATTERNS = [
    (r"stage\s*(?:IV|4)", "4"),
    (r"stage\s*(?:III|3)", "3"),
    (r"stage\s*(?:II|2)", "2"),
    (r"unstageable", "unstageable"),
]

DRAINAGE_PATTERNS = [
    (r"drainage[:\s]*(none|absent)", "none"),
    (r"no\s*(drainage|exudate)", "none"),
    (r"drainage[:\s]*light", "light"),
    (r"drainage[:\s]*moderate", "moderate"),
    (r"drainage[:\s]*heavy", "heavy"),
    (r"(light|minimal|scant|slight|min)\s*(drainage|exudate|serosang|serous)", "light"),
    (r"(moderate|mod)\s*(drainage|exudate|serosang|serous)", "moderate"),
    (r"(heavy|large|copious)\s*(drainage|exudate|serosang|serous)", "heavy"),
    (r"drainage\s*present\s*[-–]\s*\w+,?\s*(light|minimal|scant)", "light"),
    (r"drainage\s*present\s*[-–]\s*\w+,?\s*(moderate)", "moderate"),
    (r"drainage\s*present\s*[-–]\s*\w+,?\s*(heavy)", "heavy"),
    (r"drainage[:\s]*\w+,\s*(light|minimal)", "light"),
    (r"drainage[:\s]*\w+,\s*(moderate)", "moderate"),
    (r"drainage[:\s]*\w+,\s*(heavy)", "heavy"),
]

LOCATION_PATTERNS = [
    r"(?:location|site)[:\s]*([\w\s]+?)(?:\n|$|,|\.)",
    r"(?:ulcer|wound|injury)\s+(?:to|on|at)\s+([\w\s]+?)(?:\s*/|\s*,|\s*\.|$|\s*measures|\s*meas)",
    r"(?:to|on|at)\s+((?:right|left|bilateral|[rl])\s+[\w\s]+?)(?:\s*/|\s*,|\s*\.|$|\s*measures|\s*meas)",
    r"(sacr\w+|heel|coccyx|buttock|trochanter\w*|ankle|foot|toe|shin|calf|thigh|hip|elbow|shoulder|back|lower\s*leg|plantar|lateral\s+\w+|left\s+\w+|right\s+\w+|dorsal\s+\w+|medial\s+\w+)",
]


def extract_wound_type(text):
    text_lower = text.lower()
    for pattern, wound_type in WOUND_TYPE_PATTERNS:
        if re.search(pattern, text_lower):
            return wound_type
    return None


def extract_stage(text):
    text_lower = text.lower()
    for pattern, stage in STAGE_PATTERNS:
        if re.search(pattern, text_lower):
            return stage
    return None


def extract_location(text):
    for pattern in LOCATION_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None


def extract_measurements(text):
    length, width, depth = None, None, None

    lm = re.search(r"length[:\s(]*(\d+\.?\d*)\s*cm", text, re.IGNORECASE)
    wm = re.search(r"width[:\s(]*(\d+\.?\d*)\s*cm", text, re.IGNORECASE)
    dm = re.search(r"depth[:\s(]*(\d+\.?\d*)\s*cm", text, re.IGNORECASE)

    if lm:
        length = float(lm.group(1))
    if wm:
        width = float(wm.group(1))
    if dm:
        depth = float(dm.group(1))

    if length is None or width is None:
        # 3-part: Meas 8.0x3.5x0.2cm or measures 4.3 cm x 1.8 cm x 0.3 cm
        combo3 = re.search(
            r"(?:meas(?:ures?|urements?)?)\s*(?:aprx\s*)?(\d+\.?\d*)\s*(?:cm\s*)?[x×]\s*(\d+\.?\d*)\s*(?:cm\s*)?[x×]\s*(\d+\.?\d*)\s*cm",
            text, re.IGNORECASE
        )
        if combo3:
            length = length or float(combo3.group(1))
            width = width or float(combo3.group(2))
            depth = depth or float(combo3.group(3))

    if length is None or width is None:
        # 2-part: Measures 2.9 cm x 2.8 cm
        combo2 = re.search(
            r"(?:meas(?:ures?|urements?)?)\s*(?:aprx\s*)?(\d+\.?\d*)\s*(?:cm\s*)?[x×]\s*(\d+\.?\d*)\s*cm",
            text, re.IGNORECASE
        )
        if combo2:
            length = length or float(combo2.group(1))
            width = width or float(combo2.group(2))

    if length is None or width is None:
        # Generic LxWxD pattern anywhere
        generic3 = re.search(
            r"(\d+\.?\d*)\s*(?:cm\s*)?[x×]\s*(\d+\.?\d*)\s*(?:cm\s*)?[x×]\s*(\d+\.?\d*)\s*cm",
            text, re.IGNORECASE
        )
        if generic3:
            length = length or float(generic3.group(1))
            width = width or float(generic3.group(2))
            depth = depth or float(generic3.group(3))

    if length is None or width is None:
        # Generic LxW pattern
        generic2 = re.search(
            r"(\d+\.?\d*)\s*(?:cm\s*)?[x×]\s*(\d+\.?\d*)\s*cm",
            text, re.IGNORECASE
        )
        if generic2:
            length = length or float(generic2.group(1))
            width = width or float(generic2.group(2))

    if depth is None:
        # Standalone depth: "depth 1.8cm" or "0.9cm deep"
        dm2 = re.search(r"depth\s*(\d+\.?\d*)\s*cm", text, re.IGNORECASE)
        if dm2:
            depth = float(dm2.group(1))
        else:
            dm3 = re.search(r"(\d+\.?\d*)\s*cm\s*deep", text, re.IGNORECASE)
            if dm3:
                depth = float(dm3.group(1))

    return length, width, depth


def extract_drainage(text):
    text_lower = text.lower()
    for pattern, drainage in DRAINAGE_PATTERNS:
        if re.search(pattern, text_lower):
            return drainage
    return None


def regex_extract(text):
    length, width, depth = extract_measurements(text)
    return {
        "wound_type": extract_wound_type(text),
        "wound_stage": extract_stage(text),
        "location": extract_location(text),
        "length_cm": length,
        "width_cm": width,
        "depth_cm": depth,
        "drainage": extract_drainage(text),
    }


def is_complete(fields):
    required = ["wound_type", "location", "length_cm", "width_cm", "depth_cm", "drainage"]
    return all(fields.get(k) is not None for k in required)


def llm_extract(text):
    if not LLM_ENABLED:
        return None

    if CLAUDE_AVAILABLE and os.environ.get("ANTHROPIC_API_KEY"):
        try:
            client = anthropic.Anthropic()
            response = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=300,
                messages=[{"role": "user", "content": f"""Extract wound details from this clinical note. Return ONLY valid JSON with these fields:
- wound_type: one of (pressure_ulcer, diabetic_foot_ulcer, venous_stasis_ulcer, arterial_ulcer, surgical_site_infection, abscess, burn) or null
- wound_stage: for pressure ulcers only (2, 3, 4, unstageable) or null
- location: anatomical location (e.g. "Sacrum", "Left heel") or null
- length_cm: number or null
- width_cm: number or null
- depth_cm: number or null
- drainage: one of (none, light, moderate, heavy) or null

Clinical note:
{text}

JSON:"""}]
            )
            content = response.content[0].text
        except Exception as e:
            print(f"  [LLM] Claude error: {e}")
            return None
    else:
        try:
            import ollama
            response = ollama.chat(model="mistral", messages=[
                {"role": "user", "content": f"""Extract wound details from this clinical note. Return ONLY valid JSON with these fields:
- wound_type: one of (pressure_ulcer, diabetic_foot_ulcer, venous_stasis_ulcer, arterial_ulcer, surgical_site_infection, abscess, burn) or null
- wound_stage: for pressure ulcers only (2, 3, 4, unstageable) or null
- location: anatomical location (e.g. "Sacrum", "Left heel") or null
- length_cm: number or null
- width_cm: number or null
- depth_cm: number or null
- drainage: one of (none, light, moderate, heavy) or null

Clinical note:
{text}

JSON:"""}]
            )
            content = response["message"]["content"]
        except Exception as e:
            print(f"  [LLM] Ollama error: {e}")
            return None

    try:
        json_match = re.search(r"\{[^{}]*\}", content, re.DOTALL)
        if json_match:
            parsed = json.loads(json_match.group())
            return {
                "wound_type": parsed.get("wound_type"),
                "wound_stage": str(parsed["wound_stage"]) if parsed.get("wound_stage") else None,
                "location": parsed.get("location"),
                "length_cm": float(parsed["length_cm"]) if parsed.get("length_cm") else None,
                "width_cm": float(parsed["width_cm"]) if parsed.get("width_cm") else None,
                "depth_cm": float(parsed["depth_cm"]) if parsed.get("depth_cm") else None,
                "drainage": parsed.get("drainage"),
            }
    except Exception as e:
        print(f"  [LLM] Parse error: {e}")

    return None


def extract_from_assessment(raw_json_str):
    try:
        data = json.loads(raw_json_str)

        # Flat format (simple keys)
        if "wound_type" in data:
            stage = data.get("stage")
            return {
                "wound_type": data.get("wound_type"),
                "wound_stage": str(stage) if stage else None,
                "location": data.get("location"),
                "length_cm": float(data["length_cm"]) if data.get("length_cm") else None,
                "width_cm": float(data["width_cm"]) if data.get("width_cm") else None,
                "depth_cm": float(data["depth_cm"]) if data.get("depth_cm") else None,
                "drainage": data.get("drainage_amount") or data.get("drainage"),
            }

        # Nested Q&A format (sections -> questions -> answer)
        if "sections" in data:
            qa = {}
            for section in data["sections"]:
                for q in section.get("questions", []):
                    key = q.get("question", "").lower().strip()
                    val = q.get("answer", "")
                    qa[key] = val

            wound_type = qa.get("wound type", "")
            wound_type_mapped = None
            wt_lower = wound_type.lower()
            for pattern, wtype in WOUND_TYPE_PATTERNS:
                if re.search(pattern, wt_lower):
                    wound_type_mapped = wtype
                    break
            if not wound_type_mapped and wound_type:
                if "venous" in wt_lower:
                    wound_type_mapped = "venous_stasis_ulcer"
                elif "pressure" in wt_lower:
                    wound_type_mapped = "pressure_ulcer"
                elif "diabetic" in wt_lower:
                    wound_type_mapped = "diabetic_foot_ulcer"
                elif "burn" in wt_lower:
                    wound_type_mapped = "burn"
                elif "abscess" in wt_lower:
                    wound_type_mapped = "abscess"

            stage = qa.get("stage", "")
            stage_val = None
            if stage and stage != "N/A":
                sm = re.search(r"(\d+|unstageable)", stage, re.IGNORECASE)
                if sm:
                    stage_val = sm.group(1)

            location = qa.get("location", "") or None

            def safe_float(key):
                v = qa.get(key, "")
                try:
                    return float(v) if v else None
                except (ValueError, TypeError):
                    return None

            length_cm = safe_float("length (cm)")
            width_cm = safe_float("width (cm)")
            depth_cm = safe_float("depth (cm)")

            drainage_amount = qa.get("drainage amount", "") or qa.get("amount", "")
            drainage = None
            if drainage_amount:
                dl = drainage_amount.lower()
                if "heavy" in dl or "large" in dl:
                    drainage = "heavy"
                elif "moderate" in dl or "mod" in dl:
                    drainage = "moderate"
                elif "light" in dl or "minimal" in dl or "scant" in dl:
                    drainage = "light"
                elif "none" in dl or "absent" in dl:
                    drainage = "none"
                else:
                    drainage = drainage_amount.lower()

            # If no structured drainage, try the wound narrative
            if not drainage:
                narrative = qa.get("wound narrative", "")
                if narrative:
                    drainage = extract_drainage(narrative)

            # If no structured fields, fall back to parsing narrative
            if not wound_type_mapped:
                narrative = qa.get("wound narrative", "")
                if narrative:
                    return regex_extract(narrative)

            return {
                "wound_type": wound_type_mapped,
                "wound_stage": stage_val,
                "location": location,
                "length_cm": length_cm,
                "width_cm": width_cm,
                "depth_cm": depth_cm,
                "drainage": drainage,
            }

    except (json.JSONDecodeError, TypeError) as e:
        return None


def run_extraction():
    conn = get_connection()

    conn.execute("DELETE FROM wound_extractions")
    conn.commit()

    notes = conn.execute("SELECT id, patient_id, note_text FROM raw_notes WHERE note_text IS NOT NULL").fetchall()
    print(f"[EXTRACT] Processing {len(notes)} notes...")

    patient_id_map = {}
    for row in conn.execute("SELECT id, patient_id FROM raw_patients"):
        patient_id_map[row["id"]] = row["patient_id"]

    for note in notes:
        text = note["note_text"]
        internal_id = note["patient_id"]
        pid = patient_id_map.get(internal_id, str(internal_id))

        fields = regex_extract(text)
        method = "regex"
        confidence = "high"

        if not is_complete(fields):
            llm_fields = llm_extract(text)
            if llm_fields:
                for key, val in llm_fields.items():
                    if fields.get(key) is None and val is not None:
                        fields[key] = val
                method = "regex+llm"
                confidence = "medium"
            else:
                confidence = "low"

        if fields["wound_type"] is not None:
            extraction = {
                "patient_id": pid,
                "source_type": "note",
                "source_id": note["id"],
                **fields,
                "extraction_method": method,
                "confidence": confidence,
                "raw_text": text[:500],
            }
            upsert_wound_extraction(conn, extraction)
            print(f"  {pid} note#{note['id']}: {fields['wound_type']} [{method}] ({confidence})")

    assessments = conn.execute(
        "SELECT id, patient_id, raw_json FROM raw_assessments WHERE raw_json IS NOT NULL"
    ).fetchall()
    print(f"\n[EXTRACT] Processing {len(assessments)} assessments...")

    for assess in assessments:
        internal_id = assess["patient_id"]
        pid = patient_id_map.get(internal_id, str(internal_id))

        fields = extract_from_assessment(assess["raw_json"])
        if fields and fields.get("wound_type"):
            extraction = {
                "patient_id": pid,
                "source_type": "assessment",
                "source_id": assess["id"],
                **fields,
                "extraction_method": "structured",
                "confidence": "high",
                "raw_text": assess["raw_json"][:500],
            }
            upsert_wound_extraction(conn, extraction)
            print(f"  {pid} assess#{assess['id']}: {fields['wound_type']} [structured]")

    conn.commit()
    conn.close()
    print("\n[EXTRACT] Done.")


if __name__ == "__main__":
    run_extraction()
