"""Throwaway multi-visit census (Phase 2, Step 0).

Scans ALL patients across facilities 101/102/103 and reports counts only.
Writes nothing to any DB. Answers one question: does ANY patient have enough
dated records (3+ notes or 3+ assessments) to support trajectory analysis?

Run:
    python -m pipeline.census

The Phase 1 probe found 1 assessment + <=2 notes per patient on a 9-patient
sample. This confirms (or refutes) that negative across the full ~300.
"""

from __future__ import annotations

from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

from .config import FACILITY_IDS
from .pcc_client import PCCClient

MAX_WORKERS = 8


class PatientCensus:
    """Counts for one patient. ``None`` means the fetch failed all retries."""

    def __init__(self, patient_id: str, internal_id: int, facility_id: int):
        self.patient_id = patient_id
        self.internal_id = internal_id
        self.facility_id = facility_id
        self.n_notes: int | None = None
        self.n_assessments: int | None = None


def _count_for_patient(client: PCCClient, pc: PatientCensus) -> PatientCensus:
    """Populate note/assessment counts; record None on post-retry failure."""
    try:
        pc.n_notes = len(client.get_notes(pc.internal_id))
    except Exception as exc:  # noqa: BLE001 - census: record failure, continue
        print(f"  ! notes fetch failed for {pc.patient_id} (id={pc.internal_id}): "
              f"{type(exc).__name__}: {exc}")
    try:
        pc.n_assessments = len(client.get_assessments(pc.internal_id))
    except Exception as exc:  # noqa: BLE001
        print(f"  ! assessments fetch failed for {pc.patient_id} (id={pc.internal_id}): "
              f"{type(exc).__name__}: {exc}")
    return pc


def _histogram(counts: list[int]) -> str:
    """Tally a list of small non-negative ints into a 0,1,2,3,4+ bucket string."""
    buckets: Counter[str] = Counter()
    for c in counts:
        key = str(c) if c < 4 else "4+"
        buckets[key] += 1
    ordered = ["0", "1", "2", "3", "4+"]
    return "  ".join(f"{k}:{buckets.get(k, 0)}" for k in ordered)


def run_census() -> list[PatientCensus]:
    patients: list[PatientCensus] = []

    with PCCClient() as client:
        # 1. Enumerate all patients across facilities.
        for facility_id in FACILITY_IDS:
            try:
                roster = client.get_patients(facility_id)
            except Exception as exc:  # noqa: BLE001
                print(f"Facility {facility_id}: could not list patients ({exc}); skipping.")
                continue
            print(f"Facility {facility_id}: {len(roster)} patients.")
            for p in roster:
                patients.append(PatientCensus(p["patient_id"], p["id"], facility_id))

        print(f"\nTotal patients enumerated: {len(patients)}")
        print(f"Fetching notes + assessments counts ({MAX_WORKERS} workers)...\n")

        # 2. Fetch counts concurrently (each call retries 429s internally).
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = {pool.submit(_count_for_patient, client, pc): pc for pc in patients}
            done = 0
            for fut in as_completed(futures):
                fut.result()
                done += 1
                if done % 50 == 0:
                    print(f"  ...{done}/{len(patients)} patients done")

    return patients


def report(patients: list[PatientCensus]) -> tuple[int, int]:
    """Print the census report. Returns (n_3plus_notes, n_3plus_assessments)."""
    print("\n" + "=" * 78)
    print("CENSUS REPORT")
    print("=" * 78)

    # Per-facility + overall summaries.
    by_facility: dict[int, list[PatientCensus]] = {}
    for pc in patients:
        by_facility.setdefault(pc.facility_id, []).append(pc)

    note_counts: list[int] = []
    assess_counts: list[int] = []
    notes_failed = 0
    assess_failed = 0

    for pc in patients:
        if pc.n_notes is None:
            notes_failed += 1
        else:
            note_counts.append(pc.n_notes)
        if pc.n_assessments is None:
            assess_failed += 1
        else:
            assess_counts.append(pc.n_assessments)

    def _avg(xs: list[int]) -> float:
        return sum(xs) / len(xs) if xs else 0.0

    for facility_id in sorted(by_facility):
        group = by_facility[facility_id]
        n = [pc.n_notes for pc in group if pc.n_notes is not None]
        a = [pc.n_assessments for pc in group if pc.n_assessments is not None]
        print(f"\nFacility {facility_id} ({len(group)} patients):")
        print(f"  notes:       avg={_avg(n):.2f} min={min(n) if n else '-'} "
              f"max={max(n) if n else '-'}")
        print(f"  assessments: avg={_avg(a):.2f} min={min(a) if a else '-'} "
              f"max={max(a) if a else '-'}")

    print("\n" + "-" * 78)
    print("OVERALL")
    print("-" * 78)
    print(f"Patients: {len(patients)}  (notes fetch-failed: {notes_failed}, "
          f"assessments fetch-failed: {assess_failed})")
    print(f"Notes per patient:       avg={_avg(note_counts):.2f} "
          f"min={min(note_counts) if note_counts else '-'} "
          f"max={max(note_counts) if note_counts else '-'}")
    print(f"Assessments per patient: avg={_avg(assess_counts):.2f} "
          f"min={min(assess_counts) if assess_counts else '-'} "
          f"max={max(assess_counts) if assess_counts else '-'}")

    print(f"\nNotes-per-patient distribution:       {_histogram(note_counts)}")
    print(f"Assessments-per-patient distribution: {_histogram(assess_counts)}")

    n_3plus_notes = sum(1 for c in note_counts if c >= 3)
    n_3plus_assess = sum(1 for c in assess_counts if c >= 3)
    print(f"\nPatients with >=3 notes:       {n_3plus_notes}")
    print(f"Patients with >=3 assessments: {n_3plus_assess}")

    return n_3plus_notes, n_3plus_assess


def main() -> None:
    patients = run_census()
    n_notes, n_assess = report(patients)

    print("\n" + "=" * 78)
    threshold = 5
    if n_notes >= threshold or n_assess >= threshold:
        print(f"VERDICT: SURPRISING — {n_notes} patients have 3+ notes and "
              f"{n_assess} have 3+ assessments (threshold {threshold}). "
              f"Trajectory analysis may be viable. STOP and review.")
    else:
        print(f"VERDICT: As expected — fewer than {threshold} patients have 3+ "
              f"records (notes: {n_notes}, assessments: {n_assess}). "
              f"Trajectory flags stay cut. Continue to Step 1.")
    print("=" * 78)


if __name__ == "__main__":
    main()
