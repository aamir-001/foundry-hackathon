import sqlite3
import json
from datetime import datetime

DB_PATH = "hackathon.db"


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS raw_patients (
            id INTEGER PRIMARY KEY,
            facility_id INTEGER,
            patient_id TEXT UNIQUE,
            first_name TEXT,
            last_name TEXT,
            birth_date TEXT,
            gender TEXT,
            primary_payer_code TEXT,
            last_modified_at TEXT,
            is_new_admission BOOLEAN,
            fetched_at TEXT
        );

        CREATE TABLE IF NOT EXISTS raw_diagnoses (
            id INTEGER PRIMARY KEY,
            patient_id TEXT,
            icd10_code TEXT,
            icd10_description TEXT,
            clinical_status TEXT,
            onset_date TEXT,
            last_modified_at TEXT,
            fetched_at TEXT
        );

        CREATE TABLE IF NOT EXISTS raw_coverage (
            id INTEGER PRIMARY KEY,
            patient_id TEXT,
            payer_name TEXT,
            payer_code TEXT,
            payer_type TEXT,
            effective_from TEXT,
            effective_to TEXT,
            last_modified_at TEXT,
            fetched_at TEXT
        );

        CREATE TABLE IF NOT EXISTS raw_notes (
            id INTEGER PRIMARY KEY,
            patient_id INTEGER,
            org_id TEXT,
            pcc_note_id INTEGER,
            note_type TEXT,
            effective_date TEXT,
            note_text TEXT,
            created_by TEXT,
            note_label TEXT,
            sync_version INTEGER,
            is_current BOOLEAN,
            fetched_at TEXT
        );

        CREATE TABLE IF NOT EXISTS raw_assessments (
            id INTEGER PRIMARY KEY,
            patient_id INTEGER,
            org_id TEXT,
            pcc_assessment_id INTEGER,
            assessment_type TEXT,
            status TEXT,
            assessment_date TEXT,
            completion_date TEXT,
            template_id INTEGER,
            assessment_type_description TEXT,
            raw_json TEXT,
            sync_version INTEGER,
            is_current BOOLEAN,
            fetched_at TEXT
        );

        CREATE TABLE IF NOT EXISTS api_fetch_status (
            patient_id TEXT,
            endpoint_name TEXT,
            status TEXT,
            attempt_count INTEGER,
            last_error TEXT,
            fetched_at TEXT,
            PRIMARY KEY (patient_id, endpoint_name)
        );

        CREATE TABLE IF NOT EXISTS wound_extractions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id TEXT,
            source_type TEXT,
            source_id INTEGER,
            wound_type TEXT,
            wound_stage TEXT,
            location TEXT,
            length_cm REAL,
            width_cm REAL,
            depth_cm REAL,
            drainage TEXT,
            extraction_method TEXT,
            confidence TEXT,
            raw_text TEXT,
            extracted_at TEXT
        );

        CREATE TABLE IF NOT EXISTS eligibility_decisions (
            patient_id TEXT PRIMARY KEY,
            internal_id INTEGER,
            first_name TEXT,
            last_name TEXT,
            facility_id INTEGER,
            has_medicare_b BOOLEAN,
            has_active_wound BOOLEAN,
            wound_type TEXT,
            wound_stage TEXT,
            wound_location TEXT,
            length_cm REAL,
            width_cm REAL,
            depth_cm REAL,
            drainage TEXT,
            sync_complete BOOLEAN,
            failed_endpoints TEXT,
            decision TEXT,
            reason TEXT,
            compliance_flags TEXT,
            flag_count INTEGER DEFAULT 0,
            decided_at TEXT
        );
    """)

    # Migration: add flag columns if upgrading an existing DB
    existing_cols = [r[1] for r in cursor.execute("PRAGMA table_info(eligibility_decisions)").fetchall()]
    if "compliance_flags" not in existing_cols:
        cursor.execute("ALTER TABLE eligibility_decisions ADD COLUMN compliance_flags TEXT")
    if "flag_count" not in existing_cols:
        cursor.execute("ALTER TABLE eligibility_decisions ADD COLUMN flag_count INTEGER DEFAULT 0")

    conn.commit()
    conn.close()


def upsert_patient(conn, patient):
    conn.execute("""
        INSERT INTO raw_patients (id, facility_id, patient_id, first_name, last_name,
            birth_date, gender, primary_payer_code, last_modified_at, is_new_admission, fetched_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            facility_id=excluded.facility_id, patient_id=excluded.patient_id,
            first_name=excluded.first_name, last_name=excluded.last_name,
            birth_date=excluded.birth_date, gender=excluded.gender,
            primary_payer_code=excluded.primary_payer_code,
            last_modified_at=excluded.last_modified_at,
            is_new_admission=excluded.is_new_admission, fetched_at=excluded.fetched_at
    """, (
        patient["id"], patient["facility_id"], patient["patient_id"],
        patient.get("first_name"), patient.get("last_name"),
        patient.get("birth_date"), patient.get("gender"),
        patient.get("primary_payer_code"), patient.get("last_modified_at"),
        patient.get("is_new_admission"), datetime.now().isoformat()
    ))


def upsert_diagnosis(conn, diag):
    conn.execute("""
        INSERT INTO raw_diagnoses (id, patient_id, icd10_code, icd10_description,
            clinical_status, onset_date, last_modified_at, fetched_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            icd10_code=excluded.icd10_code, icd10_description=excluded.icd10_description,
            clinical_status=excluded.clinical_status, onset_date=excluded.onset_date,
            last_modified_at=excluded.last_modified_at, fetched_at=excluded.fetched_at
    """, (
        diag["id"], diag["patient_id"], diag.get("icd10_code"),
        diag.get("icd10_description"), diag.get("clinical_status"),
        diag.get("onset_date"), diag.get("last_modified_at"),
        datetime.now().isoformat()
    ))


def upsert_coverage(conn, cov):
    conn.execute("""
        INSERT INTO raw_coverage (id, patient_id, payer_name, payer_code, payer_type,
            effective_from, effective_to, last_modified_at, fetched_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            payer_name=excluded.payer_name, payer_code=excluded.payer_code,
            payer_type=excluded.payer_type, effective_from=excluded.effective_from,
            effective_to=excluded.effective_to, last_modified_at=excluded.last_modified_at,
            fetched_at=excluded.fetched_at
    """, (
        cov["id"], cov["patient_id"], cov.get("payer_name"),
        cov.get("payer_code"), cov.get("payer_type"),
        cov.get("effective_from"), cov.get("effective_to"),
        cov.get("last_modified_at"), datetime.now().isoformat()
    ))


def upsert_note(conn, note):
    conn.execute("""
        INSERT INTO raw_notes (id, patient_id, org_id, pcc_note_id, note_type,
            effective_date, note_text, created_by, note_label, sync_version, is_current, fetched_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            note_text=excluded.note_text, effective_date=excluded.effective_date,
            note_type=excluded.note_type, created_by=excluded.created_by,
            note_label=excluded.note_label, sync_version=excluded.sync_version,
            is_current=excluded.is_current, fetched_at=excluded.fetched_at
    """, (
        note["id"], note["patient_id"], note.get("org_id"),
        note.get("pcc_note_id"), note.get("note_type"),
        note.get("effective_date"), note.get("note_text"),
        note.get("created_by"), note.get("note_label"),
        note.get("sync_version"), note.get("is_current"),
        datetime.now().isoformat()
    ))


def upsert_assessment(conn, assess):
    conn.execute("""
        INSERT INTO raw_assessments (id, patient_id, org_id, pcc_assessment_id,
            assessment_type, status, assessment_date, completion_date, template_id,
            assessment_type_description, raw_json, sync_version, is_current, fetched_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            assessment_type=excluded.assessment_type, status=excluded.status,
            assessment_date=excluded.assessment_date, completion_date=excluded.completion_date,
            raw_json=excluded.raw_json, sync_version=excluded.sync_version,
            is_current=excluded.is_current, fetched_at=excluded.fetched_at
    """, (
        assess["id"], assess["patient_id"], assess.get("org_id"),
        assess.get("pcc_assessment_id"), assess.get("assessment_type"),
        assess.get("status"), assess.get("assessment_date"),
        assess.get("completion_date"), assess.get("template_id"),
        assess.get("assessment_type_description"), assess.get("raw_json"),
        assess.get("sync_version"), assess.get("is_current"),
        datetime.now().isoformat()
    ))


def upsert_fetch_status(conn, patient_id, endpoint_name, status, attempts, error=None):
    conn.execute("""
        INSERT INTO api_fetch_status (patient_id, endpoint_name, status, attempt_count, last_error, fetched_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(patient_id, endpoint_name) DO UPDATE SET
            status=excluded.status, attempt_count=excluded.attempt_count,
            last_error=excluded.last_error, fetched_at=excluded.fetched_at
    """, (patient_id, endpoint_name, status, attempts, error, datetime.now().isoformat()))


def upsert_wound_extraction(conn, extraction):
    conn.execute("""
        INSERT INTO wound_extractions (patient_id, source_type, source_id, wound_type,
            wound_stage, location, length_cm, width_cm, depth_cm, drainage,
            extraction_method, confidence, raw_text, extracted_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        extraction["patient_id"], extraction["source_type"], extraction["source_id"],
        extraction.get("wound_type"), extraction.get("wound_stage"),
        extraction.get("location"), extraction.get("length_cm"),
        extraction.get("width_cm"), extraction.get("depth_cm"),
        extraction.get("drainage"), extraction["extraction_method"],
        extraction.get("confidence"), extraction.get("raw_text"),
        datetime.now().isoformat()
    ))


def upsert_eligibility(conn, decision):
    conn.execute("""
        INSERT INTO eligibility_decisions (patient_id, internal_id, first_name, last_name,
            facility_id, has_medicare_b, has_active_wound, wound_type, wound_stage,
            wound_location, length_cm, width_cm, depth_cm, drainage,
            sync_complete, failed_endpoints, decision, reason,
            compliance_flags, flag_count, decided_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(patient_id) DO UPDATE SET
            has_medicare_b=excluded.has_medicare_b, has_active_wound=excluded.has_active_wound,
            wound_type=excluded.wound_type, wound_stage=excluded.wound_stage,
            wound_location=excluded.wound_location, length_cm=excluded.length_cm,
            width_cm=excluded.width_cm, depth_cm=excluded.depth_cm, drainage=excluded.drainage,
            sync_complete=excluded.sync_complete, failed_endpoints=excluded.failed_endpoints,
            decision=excluded.decision, reason=excluded.reason,
            compliance_flags=excluded.compliance_flags, flag_count=excluded.flag_count,
            decided_at=excluded.decided_at
    """, (
        decision["patient_id"], decision["internal_id"],
        decision.get("first_name"), decision.get("last_name"),
        decision["facility_id"], decision["has_medicare_b"],
        decision["has_active_wound"], decision.get("wound_type"),
        decision.get("wound_stage"), decision.get("wound_location"),
        decision.get("length_cm"), decision.get("width_cm"),
        decision.get("depth_cm"), decision.get("drainage"),
        decision["sync_complete"], decision.get("failed_endpoints"),
        decision["decision"], decision["reason"],
        decision.get("compliance_flags"), decision.get("flag_count", 0),
        datetime.now().isoformat()
    ))
