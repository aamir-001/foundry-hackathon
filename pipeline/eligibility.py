import json

from pipeline.database import get_connection, upsert_eligibility

REQUIRED_ENDPOINTS = ["coverage", "diagnoses", "notes", "assessments"]

WOUND_ICD10_PREFIXES = [
    "L89",    # pressure ulcer
    "L97",    # non-pressure chronic ulcer of lower limb
    "L98.4",  # non-pressure chronic ulcer of skin, NEC
    "E08.62", # diabetes with skin complications
    "E09.62",
    "E10.62",
    "E11.62",
    "E13.62",
    "I83.0",  # varicose veins with ulcer
    "I83.2",
    "I87.01", # postthrombotic syndrome with ulcer
    "T81.4",  # infection following procedure (surgical site)
    "L02",    # abscess
    # Burns by body site (T20-T28) and by extent (T30-T32)
    "T20", "T21", "T22", "T23", "T24", "T25", "T26", "T27", "T28",
    "T30", "T31", "T32",
]

# Stages that indicate a deep/advanced wound for audit purposes
ADVANCED_STAGES = {"3", "4", "unstageable"}


def has_active_medicare_b(conn, patient_id):
    rows = conn.execute(
        "SELECT payer_code, effective_to FROM raw_coverage WHERE patient_id = ?",
        (patient_id,)
    ).fetchall()

    for row in rows:
        if row["payer_code"] == "MCB":
            if row["effective_to"] is None:
                return True
    return False


def has_wound_diagnosis(conn, patient_id):
    rows = conn.execute(
        "SELECT icd10_code, clinical_status FROM raw_diagnoses WHERE patient_id = ?",
        (patient_id,)
    ).fetchall()

    for row in rows:
        if row["clinical_status"] != "active":
            continue
        code = row["icd10_code"] or ""
        for prefix in WOUND_ICD10_PREFIXES:
            if code.startswith(prefix):
                return True
    return False


def get_sync_status(conn, patient_id):
    rows = conn.execute(
        "SELECT endpoint_name, status FROM api_fetch_status WHERE patient_id = ?",
        (patient_id,)
    ).fetchall()

    status_map = {row["endpoint_name"]: row["status"] for row in rows}
    failed = [ep for ep in REQUIRED_ENDPOINTS if status_map.get(ep) != "success"]

    return {
        "complete": len(failed) == 0,
        "failed_endpoints": failed,
    }


def get_best_wound_extraction(conn, patient_id):
    rows = conn.execute("""
        SELECT wound_type, wound_stage, location, length_cm, width_cm, depth_cm,
               drainage, confidence, extraction_method
        FROM wound_extractions
        WHERE patient_id = ?
        ORDER BY
            CASE confidence WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
            CASE source_type WHEN 'assessment' THEN 1 ELSE 2 END
        LIMIT 1
    """, (patient_id,)).fetchall()

    if rows:
        return dict(rows[0])
    return None


def get_compliance_flags(is_new_admission, wound, has_wound_dx, has_mcb):
    """Audit / denial-risk flags layered on top of the base eligibility decision.

    Returns a list of {code, message, severity}. These are soft flags: they
    annotate a patient and can downgrade auto_accept -> flag_for_review, but
    they never upgrade a decision.
    """
    flags = []

    # Flag 3: New admission presenting with an advanced-stage wound.
    # A Stage 3/4/unstageable wound on a day-1 admission likely developed at a
    # prior facility -> present-on-admission must be documented (audit trigger).
    if is_new_admission and wound:
        stage = str(wound.get("wound_stage") or "").lower()
        if stage in ADVANCED_STAGES:
            flags.append({
                "code": "NEW_ADMIT_ADVANCED_WOUND",
                "message": f"New admission presenting with Stage {wound.get('wound_stage')} wound — "
                           f"document whether wound is present-on-admission vs. facility-acquired.",
                "severity": "review",
            })

    # Flag 4: Billable wound documented in notes/assessments but no supporting
    # wound ICD-10 diagnosis on file -> medical necessity unsupported, denial risk.
    if has_mcb and wound and wound.get("wound_type") and not has_wound_dx:
        flags.append({
            "code": "NO_WOUND_ICD10",
            "message": f"Wound ({wound.get('wound_type')}) documented but no active wound-related "
                       f"ICD-10 diagnosis on file — medical necessity unsupported.",
            "severity": "review",
        })

    return flags


def make_decision(has_mcb, has_wound, wound, sync_status):
    if not sync_status["complete"]:
        failed = ", ".join(sync_status["failed_endpoints"])
        return "flag_for_review", f"Incomplete data sync. Failed endpoints: {failed}. Cannot make reliable determination."

    if not has_mcb:
        return "reject", "Patient does not have active Medicare Part B coverage."

    if not has_wound and wound is None:
        return "reject", "No active wound diagnosis or wound documentation found."

    if wound is None:
        return "flag_for_review", "Active wound diagnosis on record but no wound details found in notes or assessments."

    missing_fields = []
    if wound.get("length_cm") is None:
        missing_fields.append("length")
    if wound.get("width_cm") is None:
        missing_fields.append("width")
    if wound.get("depth_cm") is None:
        missing_fields.append("depth")
    if wound.get("drainage") is None:
        missing_fields.append("drainage")

    if missing_fields:
        return "flag_for_review", f"Wound documented but missing measurements: {', '.join(missing_fields)}. Biller should verify."

    if wound.get("confidence") == "low":
        return "flag_for_review", "Wound data extracted with low confidence from unstructured note. Clinician should verify."

    wtype = wound.get("wound_type") or "wound"
    loc = wound.get("location") or "unspecified location"

    if wound.get("confidence") == "medium":
        return "auto_accept", f"Medicare B active. {wtype} at {loc} with complete measurements. Extracted via LLM — review recommended but billable."

    return "auto_accept", f"Medicare B active. {wtype} at {loc} with complete measurements and drainage documented. Ready for billing."


def run_eligibility():
    conn = get_connection()

    patients = conn.execute(
        "SELECT id, patient_id, first_name, last_name, facility_id, is_new_admission FROM raw_patients"
    ).fetchall()

    print(f"[ELIGIBILITY] Evaluating {len(patients)} patients...")

    counts = {"auto_accept": 0, "flag_for_review": 0, "reject": 0}
    total_flagged = 0

    for patient in patients:
        pid = patient["patient_id"]
        internal_id = patient["id"]

        mcb = has_active_medicare_b(conn, pid)
        wound_dx = has_wound_diagnosis(conn, pid)
        sync = get_sync_status(conn, pid)
        wound = get_best_wound_extraction(conn, pid)

        decision, reason = make_decision(mcb, wound_dx, wound, sync)

        # Compliance / denial-risk flags layered on top of the base decision
        flags = get_compliance_flags(bool(patient["is_new_admission"]), wound, wound_dx, mcb)
        if flags:
            total_flagged += 1
            flag_msgs = " ".join(f"[FLAG] {f['message']}" for f in flags)
            # A flag that warrants review downgrades a clean auto_accept
            if decision == "auto_accept" and any(f["severity"] == "review" for f in flags):
                decision = "flag_for_review"
                reason = f"{flag_msgs} (Auto-accept downgraded due to compliance flag.)"
            else:
                reason = f"{reason} {flag_msgs}"

        counts[decision] += 1

        record = {
            "patient_id": pid,
            "internal_id": internal_id,
            "first_name": patient["first_name"],
            "last_name": patient["last_name"],
            "facility_id": patient["facility_id"],
            "has_medicare_b": mcb,
            "has_active_wound": wound_dx,
            "wound_type": wound["wound_type"] if wound else None,
            "wound_stage": wound.get("wound_stage") if wound else None,
            "wound_location": wound.get("location") if wound else None,
            "length_cm": wound.get("length_cm") if wound else None,
            "width_cm": wound.get("width_cm") if wound else None,
            "depth_cm": wound.get("depth_cm") if wound else None,
            "drainage": wound.get("drainage") if wound else None,
            "sync_complete": sync["complete"],
            "failed_endpoints": ", ".join(sync["failed_endpoints"]) if sync["failed_endpoints"] else None,
            "decision": decision,
            "reason": reason,
            "compliance_flags": json.dumps(flags) if flags else None,
            "flag_count": len(flags),
        }
        upsert_eligibility(conn, record)

    conn.commit()
    conn.close()

    print(f"\n[ELIGIBILITY] Results:")
    print(f"  auto_accept:     {counts['auto_accept']}")
    print(f"  flag_for_review: {counts['flag_for_review']}")
    print(f"  reject:          {counts['reject']}")
    print(f"  compliance-flagged patients: {total_flagged}")
    print("[ELIGIBILITY] Done.")


if __name__ == "__main__":
    run_eligibility()
