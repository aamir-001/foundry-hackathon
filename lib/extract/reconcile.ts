import type { PatientBundle } from "@/lib/pcc/types";
import type { Extracted, ParsedSource, WoundMention } from "@/lib/extract/types";
import {
  flattenAssessment,
  isNarrativeAssessment,
  narrativeAnswer,
  parseStructured,
} from "@/lib/extract/structured";
import { parseFreeText } from "@/lib/extract/narrative";

const firstNonNull = <T>(vals: (T | null | undefined)[]): T | null => {
  for (const v of vals) if (v != null) return v as T;
  return null;
};

// Two measurements describe the same wound if L and W match closely.
function sameWound(a: WoundMention, b: WoundMention): boolean {
  return (
    a.length_cm != null &&
    b.length_cm != null &&
    Math.abs(a.length_cm - b.length_cm) < 0.06 &&
    a.width_cm != null &&
    b.width_cm != null &&
    Math.abs(a.width_cm - b.width_cm) < 0.06
  );
}

/**
 * Phase 2 (pre-recovery): build one field set per patient, preferring the
 * structured assessment, then filling gaps from the narrative + notes.
 */
export function extractPatient(bundle: PatientBundle): Extracted {
  const f = flattenAssessment(bundle.assessments[0]?.raw_json);
  const narr = isNarrativeAssessment(f);
  const assessment: ParsedSource = narr
    ? parseFreeText(narrativeAnswer(f))
    : parseStructured(f);

  // Primary note = latest by effective_date; the rest are siblings (BUILD_PLAN §8
  // recovery cascade: "primary note → sibling note"). noteSources[0] is primary.
  const sortedNotes = [...bundle.notes].sort((a, b) =>
    (b.effective_date ?? "").localeCompare(a.effective_date ?? ""),
  );
  const primaryNoteText = sortedNotes[0]?.note_text ?? "";
  const noteSources = sortedNotes.map((n) => parseFreeText(n.note_text ?? ""));

  const primary: WoundMention = { ...assessment.wounds[0] };

  // Fill depth from a note: prefer the note wound matching primary L/W, else the
  // first note wound that carries a depth at all.
  if (primary.depth_cm == null) {
    for (const s of noteSources) {
      const match =
        s.wounds.find((w) => w.depth_cm != null && sameWound(w, primary)) ??
        s.wounds.find((w) => w.depth_cm != null);
      if (match) {
        primary.depth_cm = match.depth_cm;
        break;
      }
    }
  }

  // Fill secondary fields from notes when the assessment lacks them.
  const notePrimaries = noteSources.map((s) => s.wounds[0]).filter(Boolean);
  primary.location ??= firstNonNull(notePrimaries.map((w) => w.location));
  primary.laterality ??= firstNonNull(notePrimaries.map((w) => w.laterality));
  primary.stage ??= firstNonNull(notePrimaries.map((w) => w.stage));
  primary.wound_type ??= firstNonNull(notePrimaries.map((w) => w.wound_type));

  // Drainage: prefer assessment, fall back to notes.
  const drainage_amount =
    assessment.drainage_amount ?? firstNonNull(noteSources.map((s) => s.drainage_amount));
  const drainage_type =
    assessment.drainage_type ?? firstNonNull(noteSources.map((s) => s.drainage_type));
  const drainage_present =
    assessment.drainage_present ??
    (drainage_amount == null ? null : drainage_amount !== "none");

  // Multi-wound (oracle: 64): the PRIMARY note (latest by effective_date) documents
  // ≥2 measurement sets OR carries a marker phrase. Only the primary note counts —
  // a second wound mentioned in an older sibling note is not the current picture.
  const primaryParsed = noteSources[0];
  const MARKERS = ["also eval", "both wounds", "second wound", "wound also"];
  const lowerPrimary = primaryNoteText.toLowerCase();
  const is_multi_wound =
    !!primaryParsed &&
    (primaryParsed.wounds.length >= 2 || MARKERS.some((m) => lowerPrimary.includes(m)));
  const distinct = dedupeWounds(
    [assessment.wounds[0], ...noteSources.flatMap((s) => s.wounds)].filter(Boolean),
  );

  return {
    patient_id: bundle.patient.patient_id,
    wound_type: primary.wound_type,
    stage: primary.stage,
    location: primary.location,
    laterality: primary.laterality,
    length_cm: primary.length_cm,
    width_cm: primary.width_cm,
    depth_cm: primary.depth_cm,
    drainage_present,
    drainage_type,
    drainage_amount,
    is_multi_wound,
    wounds: distinct,
    assessment_format: narr ? "narrative" : "structured",
  };
}

function dedupeWounds(wounds: WoundMention[]): WoundMention[] {
  const out: WoundMention[] = [];
  for (const w of wounds) {
    if (!out.some((o) => sameWound(o, w))) out.push(w);
  }
  return out;
}
