from datetime import datetime, timezone

WOUND_ICD10_PREFIXES = ['L89', 'L97', 'L98', 'E11.6', 'I83', 'T79']

# depth_cm removed — real API data is often 2D only
REQUIRED_FIELDS = ["wound_type", "length_cm", "width_cm", "drainage"]

def has_active_mcb(coverage_records):
    today = datetime.now(timezone.utc).date()
    for c in coverage_records:
        if c.get("payer_code") != "MCB":
            continue
        eff_to = c.get("effective_to")
        if eff_to is None:
            return True
        try:
            end = datetime.fromisoformat(eff_to.replace("Z", "+00:00")).date()
            if end >= today:
                return True
        except Exception:
            continue
    return False

def _missing_fields(wound):
    return [f for f in REQUIRED_FIELDS if not wound.get(f)]

def _has_wound_icd10(diagnoses):
    for d in diagnoses:
        if d.get("clinical_status") != "active":
            continue
        code = d.get("icd10_code", "")
        if any(code.startswith(p) for p in WOUND_ICD10_PREFIXES):
            return True
    return False

def route_patient(patient, wound, trajectory):
    fetch  = patient.get("fetch_status", {})
    payer  = patient.get("primary_payer_code", "")
    mcb    = has_active_mcb(patient.get("coverage", []))
    cov_failed    = fetch.get("coverage")    == "failed"
    notes_failed  = fetch.get("notes")       == "failed"
    assess_failed = fetch.get("assessments") == "failed"

    if cov_failed:
        return {"decision": "flag_for_review",
                "reason": "Could not verify Medicare Part B coverage — API sync incomplete. Do not route to billing until coverage is confirmed."}
    if not mcb:
        return {"decision": "reject",
                "reason": f"No active Medicare Part B. Primary payer: {payer}. Not eligible for wound care billing."}
    if notes_failed and assess_failed:
        return {"decision": "flag_for_review",
                "reason": "Medicare Part B confirmed but wound data could not be fetched. Do not bill until wound documentation is verified."}
    if not wound.get("wound_type"):
        return {"decision": "reject",
                "reason": "Could not extract wound type from available notes or assessments. Do not route to billing."}

    missing = _missing_fields(wound)
    if wound.get("note_format") == "Envive" and missing:
        return {"decision": "flag_for_review",
                "reason": f"Unstructured Envive note — could not reliably extract: {', '.join(missing)}. Clinician review required."}
    if missing:
        return {"decision": "flag_for_review",
                "reason": f"Medicare Part B confirmed but documentation incomplete. Missing: {', '.join(missing)}."}
    if not _has_wound_icd10(patient.get("diagnoses", [])):
        return {"decision": "flag_for_review",
                "reason": "No active wound-related ICD-10 diagnosis on file. Medical necessity unsupported without a matching diagnosis code."}
    if patient.get("is_new_admission") and wound.get("stage") in (3, 4, "unstageable"):
        return {"decision": "flag_for_review",
                "reason": f"New admission with Stage {wound.get('stage')} wound. Document whether wound is facility-acquired before billing."}
    if trajectory.get("compliance_flag"):
        visits = trajectory["visit_count"]
        trend  = trajectory["wound_trend"]
        chg    = trajectory.get("area_change_pct")
        chg_s  = f" ({chg:+.1f}% area change)" if chg is not None else ""
        return {"decision": "flag_for_review",
                "reason": f"Wound is '{trend}' across {visits} visits{chg_s}. Medicare requires documented healing progress — review before billing."}
    if trajectory.get("high_frequency_flag"):
        return {"decision": "flag_for_review",
                "reason": f"{trajectory['visit_count']} visits in 30 days. Unusually high billing frequency — review before submitting."}
    if trajectory.get("measurement_jump_flag"):
        return {"decision": "flag_for_review",
                "reason": "Wound area increased more than 50% between visits. May indicate measurement error — verify before billing."}

    wtype     = (wound.get("wound_type") or "").replace("_", " ").title()
    stage_str = f" Stage {wound['stage']}" if wound.get("stage") else ""
    loc_str   = f" at {wound['location']}" if wound.get("location") else ""
    trend_str = ""
    if trajectory.get("wound_trend") == "improving":
        chg = trajectory.get("area_change_pct")
        trend_str = f" Wound trending toward healing ({chg:+.1f}% area reduction)." if chg else " Wound trending toward healing."
    return {"decision": "auto_accept",
            "reason": f"Active Medicare Part B. {wtype}{stage_str}{loc_str}. All required fields documented.{trend_str} Safe to route to billing."}

def build_output_row(patient, wound, trajectory):
    routing = route_patient(patient, wound, trajectory)
    fetch   = patient.get("fetch_status", {})
    return {
        "patient_id":          patient.get("patient_id"),
        "facility_id":         patient.get("facility_id"),
        "name":                f"{patient.get('first_name','')} {patient.get('last_name','')}".strip(),
        "dob":                 patient.get("birth_date"),
        "is_new_admission":    patient.get("is_new_admission"),
        "mcb_active":          has_active_mcb(patient.get("coverage", [])),
        "primary_payer":       patient.get("primary_payer_code"),
        "wound_type":          wound.get("wound_type"),
        "stage":               wound.get("stage"),
        "location":            wound.get("location"),
        "length_cm":           wound.get("length_cm"),
        "width_cm":            wound.get("width_cm"),
        "depth_cm":            wound.get("depth_cm"),
        "drainage":            wound.get("drainage"),
        "note_format":         wound.get("note_format"),
        "extraction_source":   wound.get("source"),
        "confidence":          wound.get("confidence"),
        "visit_count":         trajectory.get("visit_count"),
        "wound_trend":         trajectory.get("wound_trend"),
        "area_change_pct":     trajectory.get("area_change_pct"),
        "compliance_flag":     trajectory.get("compliance_flag"),
        "high_frequency_flag": trajectory.get("high_frequency_flag"),
        "measurement_jump":    trajectory.get("measurement_jump_flag"),
        "fetch_coverage":      fetch.get("coverage"),
        "fetch_notes":         fetch.get("notes"),
        "fetch_assessments":   fetch.get("assessments"),
        "decision":            routing["decision"],
        "reason":              routing["reason"],
    }
