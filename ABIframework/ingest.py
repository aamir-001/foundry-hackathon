import json
import logging
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from api_client import get_patients, get_diagnoses, get_coverage, get_notes, get_assessments

log = logging.getLogger(__name__)
FACILITIES = [101, 102, 103]
NON_MCB_PAYERS = {"HMO", "MCA", "MCD"}
DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

def _fetch_one_patient(patient):
    pid_str = patient["patient_id"]
    pid_int = patient["id"]
    payer = patient.get("primary_payer_code", "")
    diagnoses, dx_status = get_diagnoses(pid_str)
    coverage, cov_status = get_coverage(pid_str)
    if payer in NON_MCB_PAYERS:
        return {**patient, "diagnoses": diagnoses, "coverage": coverage,
                "notes": [], "assessments": [],
                "fetch_status": {"diagnoses": dx_status, "coverage": cov_status,
                                 "notes": "skipped", "assessments": "skipped"}}
    notes, notes_status = get_notes(pid_int)
    assessments, assess_status = get_assessments(pid_int)
    return {**patient, "diagnoses": diagnoses, "coverage": coverage,
            "notes": notes, "assessments": assessments,
            "fetch_status": {"diagnoses": dx_status, "coverage": cov_status,
                             "notes": notes_status, "assessments": assess_status}}

def ingest_facility(facility_id, since=None):
    patients_data, status = get_patients(facility_id, since=since)
    if status == 'failed':
        log.error(f"Could not fetch patients for facility {facility_id}")
        return []
    log.info(f"Facility {facility_id}: {len(patients_data)} patients")
    enriched = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(_fetch_one_patient, p): p for p in patients_data}
        for future in as_completed(futures):
            try:
                enriched.append(future.result())
            except Exception as exc:
                log.error(f"Failed: {exc}")
    return enriched

def run_ingestion(since=None):
    all_patients = []
    for fid in FACILITIES:
        all_patients.extend(ingest_facility(fid, since=since))
    log.info(f"Total: {len(all_patients)} patients")
    with open(DATA_DIR / "raw_patients.json", "w") as f:
        json.dump(all_patients, f, indent=2, default=str)
    return all_patients
