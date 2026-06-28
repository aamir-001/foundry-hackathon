"""Supabase write layer (raw tables + ingest_status + sync_state).

Uses supabase-py. The client is built from SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY
(server-side service-role key — never the anon key, never client-side).

All writes are idempotent upserts so re-running ingestion never duplicates rows.
Row shapers map raw API JSON onto the schema columns (PRD §7); extra API fields
are dropped. ``raw_json`` (a JSON-encoded string from the API) is parsed into a
dict for the jsonb column, kept as-is (nested sections/questions, not flattened).

The two patient identifiers are kept strictly separate (CLAUDE.md hard rule 1):
- string ``patient_id`` (e.g. "FA-001") on diagnoses/coverage
- integer internal id on notes/assessments (stored in their ``patient_id`` column)
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from typing import Any

from supabase import Client, create_client

from . import config

logger = logging.getLogger(__name__)

# supabase-py / PostgREST can choke on very large single payloads; chunk batches.
BATCH_SIZE = 500


@lru_cache(maxsize=1)
def get_client() -> Client:
    """Return a cached service-role Supabase client, or raise a clear error."""
    if not config.SUPABASE_URL or not config.SUPABASE_SERVICE_ROLE_KEY:
        raise RuntimeError(
            "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in .env "
            "before running ingestion."
        )
    return create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_ROLE_KEY)


# ---------------------------------------------------------------------------
# Row shapers: raw API dict -> schema columns
# ---------------------------------------------------------------------------
def _pick(src: dict, keys: tuple[str, ...]) -> dict:
    return {k: src.get(k) for k in keys}


def shape_patient(p: dict) -> dict:
    return _pick(p, (
        "id", "facility_id", "patient_id", "first_name", "last_name",
        "birth_date", "gender", "primary_payer_code", "last_modified_at",
        "is_new_admission",
    ))


def shape_diagnosis(d: dict) -> dict:
    return _pick(d, (
        "id", "patient_id", "icd10_code", "icd10_description",
        "clinical_status", "onset_date", "last_modified_at",
    ))


def shape_coverage(c: dict) -> dict:
    return _pick(c, (
        "id", "patient_id", "payer_name", "payer_code", "payer_type",
        "effective_from", "effective_to", "last_modified_at",
    ))


def shape_note(n: dict) -> dict:
    return _pick(n, (
        "id", "patient_id", "note_type", "effective_date", "note_text",
        "created_by",
    ))


def shape_assessment(a: dict) -> dict:
    row = _pick(a, (
        "id", "patient_id", "assessment_type", "status", "assessment_date",
    ))
    row["raw_json"] = _parse_raw_json(a.get("raw_json"))
    return row


def _parse_raw_json(raw: Any) -> Any:
    """Parse the API's JSON-encoded ``raw_json`` string into a dict for jsonb.

    Kept as-is (no flattening). On parse failure, preserve the original string
    under ``_raw`` so nothing is lost.
    """
    if raw is None:
        return None
    if isinstance(raw, (dict, list)):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return {"_raw": raw}
    return {"_raw": str(raw)}


# ---------------------------------------------------------------------------
# Upserts
# ---------------------------------------------------------------------------
def _batched(rows: list[dict], size: int = BATCH_SIZE):
    for i in range(0, len(rows), size):
        yield rows[i:i + size]


def _upsert(table: str, rows: list[dict], on_conflict: str) -> int:
    if not rows:
        return 0
    client = get_client()
    total = 0
    for batch in _batched(rows):
        client.table(table).upsert(batch, on_conflict=on_conflict).execute()
        total += len(batch)
    return total


def upsert_patients(rows: list[dict]) -> int:
    return _upsert("patients", [shape_patient(r) for r in rows], on_conflict="id")


def upsert_diagnoses(rows: list[dict]) -> int:
    return _upsert("diagnoses", [shape_diagnosis(r) for r in rows], on_conflict="id")


def upsert_coverage(rows: list[dict]) -> int:
    return _upsert("coverage", [shape_coverage(r) for r in rows], on_conflict="id")


def upsert_notes(rows: list[dict]) -> int:
    return _upsert("notes", [shape_note(r) for r in rows], on_conflict="id")


def upsert_assessments(rows: list[dict]) -> int:
    return _upsert("assessments", [shape_assessment(r) for r in rows], on_conflict="id")


def upsert_ingest_status(rows: list[dict]) -> int:
    return _upsert("ingest_status", rows, on_conflict="patient_internal_id,endpoint")


def update_sync_state(endpoint: str, last_synced_at: str) -> None:
    get_client().table("sync_state").upsert(
        {"endpoint": endpoint, "last_synced_at": last_synced_at},
        on_conflict="endpoint",
    ).execute()


def count_rows(table: str) -> int:
    """Return the row count for a table (used for the post-ingest report)."""
    resp = get_client().table(table).select("*", count="exact", head=True).execute()
    return resp.count or 0
