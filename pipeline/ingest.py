from pipeline.api_client import fetch_patients, fetch_diagnoses, fetch_coverage, fetch_notes, fetch_assessments
from pipeline.database import (
    get_connection, init_db,
    upsert_patient, upsert_diagnosis, upsert_coverage,
    upsert_note, upsert_assessment, upsert_fetch_status,
)

FACILITY_IDS = [101, 102, 103]


def ingest_all():
    init_db()
    conn = get_connection()

    all_patients = []
    for fid in FACILITY_IDS:
        print(f"[INGEST] Fetching patients for facility {fid}...")
        result = fetch_patients(fid)
        if result["status"] == "success":
            patients = result["data"]
            print(f"  -> Got {len(patients)} patients")
            for p in patients:
                upsert_patient(conn, p)
                all_patients.append(p)
        else:
            print(f"  -> FAILED: {result['error']}")

    conn.commit()
    print(f"\n[INGEST] Total patients loaded: {len(all_patients)}")

    total = len(all_patients)
    for i, patient in enumerate(all_patients, 1):
        pid = patient["patient_id"]
        internal_id = patient["id"]
        print(f"\n[{i}/{total}] Processing {pid} (internal_id={internal_id})...")

        # Diagnoses (uses string patient_id)
        diag_result = fetch_diagnoses(pid)
        upsert_fetch_status(conn, pid, "diagnoses", diag_result["status"], diag_result["attempts"], diag_result["error"])
        if diag_result["status"] == "success":
            for d in diag_result["data"]:
                upsert_diagnosis(conn, d)
            print(f"  diagnoses: {len(diag_result['data'])} records")
        else:
            print(f"  diagnoses: FAILED - {diag_result['error']}")

        # Coverage (uses string patient_id)
        cov_result = fetch_coverage(pid)
        upsert_fetch_status(conn, pid, "coverage", cov_result["status"], cov_result["attempts"], cov_result["error"])
        if cov_result["status"] == "success":
            for c in cov_result["data"]:
                upsert_coverage(conn, c)
            print(f"  coverage: {len(cov_result['data'])} records")
        else:
            print(f"  coverage: FAILED - {cov_result['error']}")

        # Notes (uses integer id)
        notes_result = fetch_notes(internal_id)
        upsert_fetch_status(conn, pid, "notes", notes_result["status"], notes_result["attempts"], notes_result["error"])
        if notes_result["status"] == "success":
            for n in notes_result["data"]:
                upsert_note(conn, n)
            print(f"  notes: {len(notes_result['data'])} records")
        else:
            print(f"  notes: FAILED - {notes_result['error']}")

        # Assessments (uses integer id)
        assess_result = fetch_assessments(internal_id)
        upsert_fetch_status(conn, pid, "assessments", assess_result["status"], assess_result["attempts"], assess_result["error"])
        if assess_result["status"] == "success":
            for a in assess_result["data"]:
                upsert_assessment(conn, a)
            print(f"  assessments: {len(assess_result['data'])} records")
        else:
            print(f"  assessments: FAILED - {assess_result['error']}")

        conn.commit()

    conn.close()
    print("\n[INGEST] Done.")


if __name__ == "__main__":
    ingest_all()
