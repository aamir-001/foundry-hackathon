"""Raw ingestion: fetch all five endpoints for all patients -> Supabase.

All API access goes through ``pcc_client.py`` (CLAUDE.md hard rule 2). A fetch
that fails all retries is recorded in ``ingest_status`` as ``failed`` and never
silently dropped (hard rule 3) — ``sync_complete`` is derived from that table in
the decide phase. Re-runs are idempotent (upsert, no duplicates).

The two patient identifiers stay distinct (hard rule 1): the string ``patient_id``
keys diagnoses/coverage; the integer internal id keys notes/assessments.

Run:
    python -m pipeline.ingest
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone

from . import store
from .config import FACILITY_IDS
from .pcc_client import PCCClient

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

MAX_WORKERS = 8

# The four per-patient endpoints and how they are keyed.
STRING_KEYED = ("diagnoses", "coverage")     # keyed by string patient_id
INT_KEYED = ("notes", "assessments")         # keyed by integer internal id


@dataclass
class PatientFetch:
    """Result of fetching all child endpoints for one patient."""
    patient_id: str
    internal_id: int
    records: dict[str, list[dict]] = field(default_factory=dict)
    status: dict[str, dict] = field(default_factory=dict)  # endpoint -> status row


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fetch_endpoint(client: PCCClient, endpoint: str, pf: PatientFetch) -> None:
    """Fetch one endpoint for one patient, recording ok/failed status."""
    try:
        if endpoint == "diagnoses":
            data = client.get_diagnoses(pf.patient_id)
        elif endpoint == "coverage":
            data = client.get_coverage(pf.patient_id)
        elif endpoint == "notes":
            data = client.get_notes(pf.internal_id)
        elif endpoint == "assessments":
            data = client.get_assessments(pf.internal_id)
        else:
            raise ValueError(f"Unknown endpoint: {endpoint}")
        pf.records[endpoint] = data
        pf.status[endpoint] = _status_row(pf, endpoint, "ok", None)
    except Exception as exc:  # noqa: BLE001 - a failed fetch is recorded, not raised
        logger.warning("FETCH FAILED %s for %s (id=%s): %s",
                       endpoint, pf.patient_id, pf.internal_id, exc)
        pf.records[endpoint] = []
        pf.status[endpoint] = _status_row(pf, endpoint, "failed", f"{type(exc).__name__}: {exc}")


def _status_row(pf: PatientFetch, endpoint: str, status: str, error: str | None) -> dict:
    return {
        "patient_internal_id": pf.internal_id,
        "patient_id": pf.patient_id,
        "endpoint": endpoint,
        "status": status,
        "error": error,
        "attempts": None,  # tenacity attempt count not surfaced; status is what matters
        "fetched_at": _now_iso(),
    }


def _fetch_patient(client: PCCClient, pf: PatientFetch) -> PatientFetch:
    for endpoint in (*STRING_KEYED, *INT_KEYED):
        _fetch_endpoint(client, endpoint, pf)
    return pf


def run_ingest() -> dict:
    """Fetch and persist all raw data. Returns a summary dict for reporting."""
    summary: dict = {
        "patients": 0,
        "diagnoses": 0,
        "coverage": 0,
        "notes": 0,
        "assessments": 0,
        "failures": [],   # list of (patient_id, internal_id, endpoint, error)
    }

    with PCCClient() as client:
        # 1. Enumerate + upsert patients per facility; build the id map.
        patient_fetches: list[PatientFetch] = []
        for facility_id in FACILITY_IDS:
            try:
                roster = client.get_patients(facility_id)
            except Exception as exc:  # noqa: BLE001
                logger.error("Could not list patients for facility %s: %s", facility_id, exc)
                continue
            logger.info("Facility %s: %d patients", facility_id, len(roster))
            store.upsert_patients(roster)
            summary["patients"] += len(roster)
            for p in roster:
                patient_fetches.append(PatientFetch(p["patient_id"], p["id"]))

        store.update_sync_state("patients", _now_iso())
        logger.info("Fetching child endpoints for %d patients (%d workers)...",
                    len(patient_fetches), MAX_WORKERS)

        # 2. Fetch the four child endpoints per patient, concurrently.
        completed: list[PatientFetch] = []
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = {pool.submit(_fetch_patient, client, pf): pf for pf in patient_fetches}
            done = 0
            for fut in as_completed(futures):
                completed.append(fut.result())
                done += 1
                if done % 50 == 0:
                    logger.info("  ...%d/%d patients fetched", done, len(patient_fetches))

        # 3. Batch-upsert all records + ingest_status.
        diagnoses, coverage, notes, assessments, status_rows = [], [], [], [], []
        for pf in completed:
            diagnoses.extend(pf.records.get("diagnoses", []))
            coverage.extend(pf.records.get("coverage", []))
            notes.extend(pf.records.get("notes", []))
            assessments.extend(pf.records.get("assessments", []))
            for endpoint, row in pf.status.items():
                status_rows.append(row)
                if row["status"] == "failed":
                    summary["failures"].append(
                        (pf.patient_id, pf.internal_id, endpoint, row["error"])
                    )

        summary["diagnoses"] = store.upsert_diagnoses(diagnoses)
        summary["coverage"] = store.upsert_coverage(coverage)
        summary["notes"] = store.upsert_notes(notes)
        summary["assessments"] = store.upsert_assessments(assessments)
        store.upsert_ingest_status(status_rows)

        # 4. Record sync state per child endpoint.
        ts = _now_iso()
        for endpoint in (*STRING_KEYED, *INT_KEYED):
            store.update_sync_state(endpoint, ts)

    return summary


def _print_summary(summary: dict) -> None:
    print("\n" + "=" * 78)
    print("INGESTION SUMMARY")
    print("=" * 78)
    for table in ("patients", "diagnoses", "coverage", "notes", "assessments"):
        print(f"  {table:<14} upserted: {summary[table]}")

    failures = summary["failures"]
    print(f"\nEndpoints that failed all retries: {len(failures)}")
    for patient_id, internal_id, endpoint, error in failures:
        print(f"  - {patient_id} (id={internal_id}) {endpoint}: {error}")

    # Verify against live DB counts.
    print("\nLive row counts in Supabase:")
    for table in ("patients", "diagnoses", "coverage", "notes", "assessments",
                  "ingest_status"):
        try:
            print(f"  {table:<14} {store.count_rows(table)}")
        except Exception as exc:  # noqa: BLE001
            print(f"  {table:<14} (count failed: {exc})")
    print("=" * 78)


def main() -> None:
    summary = run_ingest()
    _print_summary(summary)


if __name__ == "__main__":
    main()
