"""Throwaway data-verification probe (Phase 1).

Pulls patients end-to-end across all five PCC endpoints and prints what we
actually find, so we can confirm data assumptions BEFORE building extraction,
decision engines, schema, or frontend.

Key questions this answers:
- Does multi-visit data exist per patient (multiple notes/assessments)?
  Several audit-risk flags (STALLED_WOUND, HIGH_VISIT_FREQUENCY, AREA_INCREASE)
  depend on it.
- What note formats actually appear (structured SPN vs Envive narrative)?
- What is the payer mix?

Run:
    python -m pipeline.verify_data

This script is intentionally disposable -- it writes nothing to any DB.
"""

from __future__ import annotations

import json
from collections import Counter

from .pcc_client import PCCClient


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def describe_shape(name: str, payload: object) -> None:
    """Print the raw shape of an API response."""
    if isinstance(payload, list):
        first_keys = sorted(payload[0].keys()) if payload and isinstance(payload[0], dict) else []
        print(f"  {name:<12} list[{len(payload)}]  keys={first_keys}")
    elif isinstance(payload, dict):
        print(f"  {name:<12} dict  keys={sorted(payload.keys())}")
    else:
        print(f"  {name:<12} {type(payload).__name__}  value={payload!r}")


def classify_note_format(note: dict) -> str:
    """Heuristically classify a note as structured vs Envive narrative.

    Phase-1 heuristic only (not the real extractor): structured notes carry an
    explicit ``note_type`` like "Wound (SPN)" / "HP Skin & Wound" and contain
    labeled fields ("Length:", "Wound Type:"). Envive notes pack everything into
    a prose paragraph with no labeled fields.
    """
    note_type = (note.get("note_type") or "").strip()
    text = note.get("note_text") or ""
    labeled_markers = ("Length:", "Wound Type:", "Location:", "Drainage:", "Width:", "Depth:")
    has_labels = any(marker in text for marker in labeled_markers)

    nt_lower = note_type.lower()
    if "envive" in nt_lower:
        return f"Envive ({note_type})"
    if has_labels or "spn" in nt_lower or "skin & wound" in nt_lower or "skin and wound" in nt_lower:
        return f"structured ({note_type or 'unlabeled'})"
    # No labels and not an obviously structured type -> treat as narrative/prose.
    return f"narrative/prose ({note_type or 'unlabeled'})"


def payer_codes_from_coverage(coverage: list[dict]) -> list[str]:
    codes = []
    for c in coverage:
        code = c.get("payer_code")
        active = c.get("effective_to") is None
        codes.append(f"{code}{'(active)' if active else '(ended)'}")
    return codes


# --------------------------------------------------------------------------
# Stage A: one patient end-to-end
# --------------------------------------------------------------------------
def probe_one_patient(client: PCCClient, facility_id: int) -> None:
    print("=" * 78)
    print(f"STAGE A — one patient end-to-end (facility {facility_id})")
    print("=" * 78)

    patients = client.get_patients(facility_id)
    if not patients:
        print(f"No patients returned for facility {facility_id}.")
        return

    patient = patients[0]
    patient_id = patient["patient_id"]          # string, e.g. FA-001
    internal_id = patient["id"]                  # integer, e.g. 1
    print(f"\nPatient: {patient_id} (internal id={internal_id}) "
          f"name={patient.get('first_name')} {patient.get('last_name')} "
          f"primary_payer_code={patient.get('primary_payer_code')} "
          f"is_new_admission={patient.get('is_new_admission')}")

    print("\nRaw response shapes:")
    describe_shape("patients", patients)

    diagnoses = client.get_diagnoses(patient_id)
    describe_shape("diagnoses", diagnoses)

    coverage = client.get_coverage(patient_id)
    describe_shape("coverage", coverage)

    notes = client.get_notes(internal_id)
    describe_shape("notes", notes)

    assessments = client.get_assessments(internal_id)
    describe_shape("assessments", assessments)

    print(f"\nMulti-visit check: notes={len(notes)}  assessments={len(assessments)}")

    print("\nNote formats:")
    if notes:
        for n in notes:
            print(f"  - id={n.get('id')} date={n.get('effective_date')} "
                  f"-> {classify_note_format(n)}")
    else:
        print("  (none)")

    print("\nPayer code(s) from /coverage:")
    print(f"  {payer_codes_from_coverage(coverage) or '(none)'}")

    # Show one raw example of each rich payload to eyeball formats.
    if notes:
        print("\nExample note_text (first note, truncated):")
        print("  " + (notes[0].get("note_text") or "")[:400].replace("\n", "\n  "))
    if assessments:
        print("\nExample assessment raw_json (first assessment):")
        raw = assessments[0].get("raw_json")
        try:
            print("  " + json.dumps(json.loads(raw), indent=2).replace("\n", "\n  "))
        except (TypeError, ValueError):
            print(f"  {raw!r}")


# --------------------------------------------------------------------------
# Stage B: sample across facilities
# --------------------------------------------------------------------------
def safe_count(fn, *args) -> int | None:
    """Call a fetch, returning len on success or None if it failed after retries.

    Mirrors the 'a failed fetch is never a clinical fact' rule: we record the
    failure and keep going rather than aborting the whole sample.
    """
    try:
        return len(fn(*args))
    except Exception as exc:  # noqa: BLE001 - probe script: log and continue
        print(f"    ! fetch failed ({fn.__name__}{args}): {type(exc).__name__}: {exc}")
        return None


def probe_sample(client: PCCClient, per_facility: int = 3) -> None:
    print("\n" + "=" * 78)
    print(f"STAGE B — sample across facilities 101/102/103 ({per_facility} per facility)")
    print("=" * 78)

    note_counts: list[int] = []
    assessment_counts: list[int] = []
    note_format_counter: Counter[str] = Counter()
    payer_counter: Counter[str] = Counter()
    sampled = 0

    for facility_id in (101, 102, 103):
        try:
            patients = client.get_patients(facility_id)
        except Exception as exc:  # noqa: BLE001
            print(f"\nFacility {facility_id}: could not list patients ({exc}); skipping.")
            continue

        print(f"\nFacility {facility_id}: {len(patients)} patients total; "
              f"sampling first {per_facility}.")

        for patient in patients[:per_facility]:
            sampled += 1
            patient_id = patient["patient_id"]
            internal_id = patient["id"]

            # Payer: prefer the primary_payer_code, but also reflect active coverage.
            primary = patient.get("primary_payer_code")
            if primary:
                payer_counter[primary] += 1

            n_notes = safe_count(client.get_notes, internal_id)
            n_assess = safe_count(client.get_assessments, internal_id)
            if n_notes is not None:
                note_counts.append(n_notes)
            if n_assess is not None:
                assessment_counts.append(n_assess)

            fmt_summary = ""
            try:
                notes = client.get_notes(internal_id)
                for n in notes:
                    note_format_counter[classify_note_format(n).split(" (")[0]] += 1
                fmt_summary = ", ".join(
                    f"{classify_note_format(n).split(' (')[0]}" for n in notes
                ) or "(no notes)"
            except Exception as exc:  # noqa: BLE001
                fmt_summary = f"(notes fetch failed: {exc})"

            print(f"  {patient_id} (id={internal_id}) payer={primary} "
                  f"notes={n_notes} assessments={n_assess}  formats=[{fmt_summary}]")

    # ---- summary ----
    print("\n" + "-" * 78)
    print("SUMMARY")
    print("-" * 78)
    print(f"Patients sampled: {sampled}")

    if note_counts:
        print(f"Notes per patient:       avg={sum(note_counts)/len(note_counts):.2f} "
              f"min={min(note_counts)} max={max(note_counts)} "
              f"(multi-visit: {sum(1 for c in note_counts if c > 1)}/{len(note_counts)})")
    if assessment_counts:
        print(f"Assessments per patient: avg={sum(assessment_counts)/len(assessment_counts):.2f} "
              f"min={min(assessment_counts)} max={max(assessment_counts)} "
              f"(multi-visit: {sum(1 for c in assessment_counts if c > 1)}/{len(assessment_counts)})")

    print("\nNote-format frequency (across all sampled notes):")
    for fmt, count in note_format_counter.most_common():
        print(f"  {fmt:<20} {count}")

    print("\nPayer mix (primary_payer_code across sampled patients):")
    for code, count in payer_counter.most_common():
        print(f"  {code:<6} {count}")


def main() -> None:
    with PCCClient() as client:
        try:
            print(f"Health check: {client.health()}")
        except Exception as exc:  # noqa: BLE001
            print(f"Health check failed: {exc}")

        probe_one_patient(client, facility_id=101)
        probe_sample(client, per_facility=3)


if __name__ == "__main__":
    main()
