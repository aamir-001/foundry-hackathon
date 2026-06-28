"""Verification harness for the extraction layer (Phase 3 checkpoint).

Runs extraction over ALL stored notes and assessments (read from Supabase; no
re-fetch from the PCC API) and reports quality, WITHOUT persisting anything:
- format distribution (count per source_format)
- confidence distribution (high / medium / low)
- how many records needed / used the LLM fallback (call volume)
- completeness (all four of L/W/D/drainage vs partial)
- 4-5 full example extractions, including an Envive note shown raw beside the
  LLM-pulled fields, and a multi-wound case showing the primary selection.

Usage:
    python -m pipeline.verify_extraction            # uses LLM if ANTHROPIC_API_KEY set
    python -m pipeline.verify_extraction --no-llm   # regex tiers only (no API calls)
    python -m pipeline.verify_extraction --limit 40 # sample for a cheap dry run
"""

from __future__ import annotations

import argparse
import textwrap
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from . import config, store
from .extract.assessments import extract_from_assessment
from .extract.format_detect import detect_format
from .extract.notes import extract_from_note
from .extract.text_fields import FMT_ENVIVE, ExtractionResult

LLM_WORKERS = 6


def _fetch_notes(limit: int | None) -> list[dict]:
    q = store.get_client().table("notes").select(
        "id, patient_id, note_type, note_text"
    ).order("id")
    if limit:
        q = q.limit(limit)
    return q.execute().data or []


def _fetch_assessments(limit: int | None) -> list[dict]:
    q = store.get_client().table("assessments").select(
        "id, patient_id, raw_json"
    ).order("id")
    if limit:
        q = q.limit(limit)
    return q.execute().data or []


def _run_notes(notes: list[dict], use_llm: bool) -> list[tuple[dict, ExtractionResult]]:
    def work(note: dict) -> tuple[dict, ExtractionResult]:
        return note, extract_from_note(note.get("note_text"), use_llm=use_llm)

    if use_llm:
        with ThreadPoolExecutor(max_workers=LLM_WORKERS) as pool:
            return list(pool.map(work, notes))
    return [work(n) for n in notes]


def _run_assessments(assessments: list[dict]) -> list[tuple[dict, ExtractionResult]]:
    # Assessments never need the LLM (structured or templated narrative).
    return [(a, extract_from_assessment(a.get("raw_json"))) for a in assessments]


def _distribution(results: list[ExtractionResult]) -> None:
    fmt = Counter(r.source_format for r in results)
    conf = Counter(r.extraction_confidence for r in results)
    complete = sum(1 for r in results if r.is_complete())
    partial = len(results) - complete
    llm_used = sum(1 for r in results if r.llm_used)
    ambiguous = sum(1 for r in results if r.ambiguous)

    print("\nFormat distribution (source_format):")
    for k, v in fmt.most_common():
        print(f"  {k:<24} {v}")
    print("\nConfidence distribution:")
    for k in ("high", "medium", "low"):
        print(f"  {k:<24} {conf.get(k, 0)}")
    print(f"\nCompleteness (all 4 of L/W/D/drainage):")
    print(f"  complete                 {complete}")
    print(f"  partial                  {partial}")
    print(f"\nLLM fallback API calls made: {llm_used}")
    print(f"Ambiguous flagged:           {ambiguous}")


def _fmt_fields(r: ExtractionResult) -> str:
    keys = ("wound_type", "stage", "location", "length_cm", "width_cm",
            "depth_cm", "drainage_amount", "extraction_confidence",
            "source_format", "ambiguous", "llm_used")
    return "\n".join(f"      {k:<22} {getattr(r, k)}" for k in keys)


def _show_example(title: str, raw_text: str, r: ExtractionResult) -> None:
    print("\n" + "-" * 78)
    print(title)
    print("-" * 78)
    print("  RAW:")
    for line in textwrap.wrap(raw_text.replace("\n", " \u23ce "), width=72):
        print(f"      {line}")
    print("  EXTRACTED:")
    print(_fmt_fields(r))
    if r.candidates:
        print("  MULTI-WOUND CANDIDATES:")
        for c in r.candidates:
            area = (c.get("length_cm") or 0) * (c.get("width_cm") or 0)
            print(f"      {c['source']:<18} "
                  f"L={c.get('length_cm')} W={c.get('width_cm')} "
                  f"D={c.get('depth_cm')} stage={c.get('stage')} area~{area:.1f}")


def _pick_examples(
    note_pairs: list[tuple[dict, ExtractionResult]],
    assess_pairs: list[tuple[dict, ExtractionResult]],
) -> None:
    print("\n" + "=" * 78)
    print("EXAMPLE EXTRACTIONS")
    print("=" * 78)

    # 1. Envive note (raw paragraph beside LLM-pulled fields).
    envive = next(
        (p for p in note_pairs if p[1].source_format == FMT_ENVIVE and p[1].llm_used),
        next((p for p in note_pairs if p[1].source_format == FMT_ENVIVE), None),
    )
    if envive:
        note, res = envive
        tag = "LLM-extracted" if res.llm_used else "LLM UNAVAILABLE (regex shell)"
        _show_example(
            f"[1] ENVIVE note id={note['id']} (note_type={note['note_type']!r}) - {tag}",
            note.get("note_text") or "", res,
        )

    # 2. Multi-wound prose (show primary selection).
    multi = next((p for p in note_pairs if p[1].candidates), None)
    if multi:
        note, res = multi
        _show_example(
            f"[2] MULTI-WOUND note id={note['id']} - primary selected by area/stage",
            note.get("note_text") or "", res,
        )

    # 3. SOAP / spn_labeled high-confidence note.
    spn = next(
        (p for p in note_pairs
         if p[1].source_format == "spn_labeled" and p[1].extraction_confidence == "high"),
        None,
    )
    if spn:
        note, res = spn
        _show_example(f"[3] SOAP/labeled note id={note['id']} - high confidence",
                      note.get("note_text") or "", res)

    # 4. Structured assessment (gold source).
    struct = next(
        (p for p in assess_pairs if p[1].source_format == "assessment_structured"), None
    )
    if struct:
        a, res = struct
        _show_example(f"[4] STRUCTURED assessment id={a['id']} - discrete Q/A fields",
                      str(a.get("raw_json")), res)

    # 5. Narrative assessment (templated, missing depth).
    narr = next(
        (p for p in assess_pairs if p[1].source_format == "assessment_narrative"), None
    )
    if narr:
        a, res = narr
        _show_example(f"[5] NARRATIVE assessment id={a['id']} - templated, no depth in source",
                      str(a.get("raw_json")), res)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-llm", action="store_true", help="regex tiers only")
    parser.add_argument("--limit", type=int, default=None, help="cap records per source")
    args = parser.parse_args()

    use_llm = (not args.no_llm) and bool(config.ANTHROPIC_API_KEY)
    if not args.no_llm and not config.ANTHROPIC_API_KEY:
        print("WARNING: ANTHROPIC_API_KEY not set -> running regex-only. Envive "
              "examples will show a shell, and LLM call volume will be 0.\n")

    notes = _fetch_notes(args.limit)
    assessments = _fetch_assessments(args.limit)
    print(f"Loaded {len(notes)} notes and {len(assessments)} assessments from Supabase.")
    print(f"LLM fallback: {'ENABLED' if use_llm else 'DISABLED'}")

    note_pairs = _run_notes(notes, use_llm)
    assess_pairs = _run_assessments(assessments)

    note_results = [r for _, r in note_pairs]
    assess_results = [r for _, r in assess_pairs]

    print("\n" + "=" * 78)
    print(f"NOTES ({len(note_results)})")
    print("=" * 78)
    _distribution(note_results)

    print("\n" + "=" * 78)
    print(f"ASSESSMENTS ({len(assess_results)})")
    print("=" * 78)
    _distribution(assess_results)

    print("\n" + "=" * 78)
    print(f"COMBINED ({len(note_results) + len(assess_results)})")
    print("=" * 78)
    _distribution(note_results + assess_results)

    _pick_examples(note_pairs, assess_pairs)


if __name__ == "__main__":
    main()
