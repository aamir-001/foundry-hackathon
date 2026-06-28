import type { PatientBundle } from "@/lib/pcc/types";
import type {
  Extracted,
  FieldStatus,
  ParsedSource,
  RecoveryResult,
  RecoveryTier,
  WoundMention,
} from "@/lib/extract/types";
import {
  flattenAssessment,
  isNarrativeAssessment,
  narrativeAnswer,
  parseStructured,
} from "@/lib/extract/structured";
import { parseFreeText } from "@/lib/extract/narrative";
import { extractPatient } from "@/lib/extract/reconcile";
import { parseLaterality } from "@/lib/extract/patterns";

// Active wound-dx ICD-10 prefixes (matches the oracle's WOUND_ICD_PREFIXES).
const WOUND_PREFIX = /^(L89|L97|L98|I83|I70|T81|L02|T2)/i;

const num = (x: unknown): number | null => {
  const n = parseFloat(String(x));
  return Number.isFinite(n) ? n : null;
};

/** First candidate with a value → present (idx 0) / recovered (idx ≥1); else unavailable. */
function resolve(cands: { value: FieldStatus["value"]; source: string }[]): FieldStatus {
  for (let i = 0; i < cands.length; i++) {
    const v = cands[i].value;
    if (v != null && !(typeof v === "string" && v.trim() === "")) {
      return { value: v, source: cands[i].source, tier: i === 0 ? "present" : "recovered" };
    }
  }
  return { value: null, source: "not in record — request from provider", tier: "unavailable" };
}

// Best depth from a parsed source: prefer the wound matching the reference L/W.
function depthFrom(src: ParsedSource | null, ref: WoundMention): number | null {
  if (!src) return null;
  const same = (w: WoundMention) =>
    w.depth_cm != null &&
    ref.length_cm != null &&
    w.length_cm != null &&
    Math.abs(w.length_cm - ref.length_cm) < 0.06 &&
    ref.width_cm != null &&
    w.width_cm != null &&
    Math.abs(w.width_cm - ref.width_cm) < 0.06;
  return (src.wounds.find(same) ?? src.wounds.find((w) => w.depth_cm != null))?.depth_cm ?? null;
}

export function recoverPatient(bundle: PatientBundle): RecoveryResult {
  const extracted: Extracted = extractPatient(bundle);
  const f = flattenAssessment(bundle.assessments[0]?.raw_json);
  const narr = isNarrativeAssessment(f);
  const assessment = narr ? parseFreeText(narrativeAnswer(f)) : parseStructured(f);
  const assessmentLabel = bundle.assessments[0]?.assessment_type ?? "assessment";

  const sortedNotes = [...bundle.notes].sort((a, b) =>
    (b.effective_date ?? "").localeCompare(a.effective_date ?? ""),
  );
  const primaryNote = sortedNotes[0] ? parseFreeText(sortedNotes[0].note_text ?? "") : null;
  const siblingNotes = sortedNotes.slice(1).map((n) => parseFreeText(n.note_text ?? ""));
  const aw = assessment.wounds[0];

  const field_status: Record<string, FieldStatus> = {};

  // wound_type / length / width — present from the assessment (always documented here).
  field_status.wound_type = resolve([{ value: extracted.wound_type, source: assessmentLabel }]);
  field_status.length_cm = resolve([{ value: extracted.length_cm, source: assessmentLabel }]);
  field_status.width_cm = resolve([{ value: extracted.width_cm, source: assessmentLabel }]);

  // depth — primary note 3-D → sibling note → structured assessment Depth (§8).
  field_status.depth_cm = resolve([
    { value: depthFrom(primaryNote, aw), source: "primary note (3-D)" },
    { value: siblingNotes.map((s) => depthFrom(s, aw)).find((d) => d != null) ?? null, source: "sibling note" },
    { value: narr ? null : num(f["Depth (cm)"]), source: assessmentLabel },
  ]);

  // location — assessment → note.
  field_status.location = resolve([
    { value: extracted.location, source: narr ? `${assessmentLabel} (narrative)` : assessmentLabel },
    { value: primaryNote?.wounds[0]?.location ?? null, source: "primary note" },
  ]);

  // stage — assessment → note (only scored for pressure ulcers; see registry).
  field_status.stage = resolve([
    { value: assessment.wounds[0]?.stage ?? null, source: assessmentLabel },
    { value: primaryNote?.wounds[0]?.stage ?? null, source: "primary note" },
  ]);

  // drainage amount — note → assessment (§8 ordering).
  field_status.drainage_amount = resolve([
    { value: primaryNote?.drainage_amount ?? null, source: "primary note" },
    { value: assessment.drainage_amount, source: assessmentLabel },
  ]);

  // laterality — assessment preferred; on conflict, suggest (present both for confirm).
  const aLat = aw?.laterality ?? null;
  const locSide = parseLaterality(extracted.location ?? "");
  const noteSide = primaryNote?.wounds[0]?.laterality ?? null;
  // Conflict only when both sides are Left/Right and differ (matches oracle E; a
  // "Bilateral" laterality vs a one-sided location is not a contradiction).
  const laterality_conflict =
    (aLat === "Left" || aLat === "Right") &&
    (locSide === "Left" || locSide === "Right") &&
    aLat !== locSide;
  if (laterality_conflict) {
    field_status.laterality = {
      value: `${aLat} (location reads ${locSide})`,
      source: "assessment vs location — confirm",
      tier: "suggested",
    };
  } else {
    field_status.laterality = resolve([
      { value: aLat, source: assessmentLabel },
      { value: noteSide, source: "primary note" },
    ]);
  }

  // wound dx code — present if an active L-code wound dx exists; else suggest one.
  const activeWoundDx = bundle.diagnoses.find(
    (d) => d.clinical_status === "active" && WOUND_PREFIX.test(d.icd10_code ?? ""),
  );
  const has_wound_dx_code = !!activeWoundDx;
  let suggested_dx_code: string | null = null;
  if (has_wound_dx_code) {
    field_status.wound_dx_code = {
      value: activeWoundDx!.icd10_code ?? null,
      source: "diagnoses",
      tier: "present",
    };
  } else {
    suggested_dx_code = suggestDxCode(extracted);
    field_status.wound_dx_code = {
      value: suggested_dx_code,
      source: "derived from type + location + stage — coder confirms",
      tier: "suggested",
    };
  }

  // multi-wound primary — suggest by diagnosis match (the assessment's documented wound).
  let suggested_primary: string | null = null;
  if (extracted.is_multi_wound) {
    suggested_primary = [extracted.wound_type, extracted.location].filter(Boolean).join(" — ") || null;
    field_status.suggested_primary = {
      value: suggested_primary,
      source: "diagnosis match — confirm primary",
      tier: "suggested",
    };
  }

  // drainage presence conflict (structured only; oracle F).
  const present = (f["Drainage Present"] ?? "").toLowerCase();
  const amt = (f["Drainage Amount"] ?? "").toLowerCase();
  const dtype = (f["Drainage Type"] ?? "").toLowerCase();
  const drainage_presence_conflict =
    (present === "no" && /serous|sang|purulent/.test(dtype)) ||
    (present === "yes" && amt === "none");

  return {
    extracted,
    field_status,
    has_wound_dx_code,
    suggested_dx_code,
    suggested_primary,
    laterality_conflict,
    drainage_presence_conflict,
  };
}

// Candidate L-code from documented type (+stage for pressure). Never auto-applied.
function suggestDxCode(e: Extracted): string {
  const loc = e.location ? ` (${e.location}${e.stage ? `, ${e.stage}` : ""})` : "";
  switch (e.wound_type) {
    case "pressure ulcer":
      return `L89.-${loc} — pressure ulcer`;
    case "diabetic foot ulcer":
      return `L97.4-/L97.5-${loc} — diabetic foot ulcer`;
    case "venous stasis ulcer":
      return `I83.0-${loc} — venous ulcer`;
    case "arterial ulcer":
      return `I70.23-${loc} — arterial ulcer`;
    case "surgical site infection":
      return `T81.4-${loc} — surgical site infection`;
    case "abscess":
      return `L02.-${loc} — abscess`;
    case "burn":
      return `T2-.-${loc} — burn`;
    default:
      return `unspecified wound code${loc}`;
  }
}

export type { RecoveryTier };
