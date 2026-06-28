import type { ParsedSource } from "@/lib/extract/types";
import { normalizeWoundType, normalizeStage } from "@/lib/extract/patterns";
import { normalizeDrainageAmount, normalizeDrainageType } from "@/lib/extract/drainage";

export type AssessmentFields = Record<string, string>;

interface RawAssessmentJson {
  sections?: { questions?: { question?: string; answer?: unknown }[] }[];
}

/** Flatten the nested `sections[].questions[]` into a {label: answer} map. */
export function flattenAssessment(rawJson: unknown): AssessmentFields {
  const o: RawAssessmentJson =
    typeof rawJson === "string" ? safeParse(rawJson) : ((rawJson as RawAssessmentJson) ?? {});
  const f: AssessmentFields = {};
  for (const s of o.sections ?? []) {
    for (const q of s.questions ?? []) {
      if (q && typeof q.question === "string") {
        f[q.question] = q.answer == null ? "" : String(q.answer);
      }
    }
  }
  return f;
}

function safeParse(s: string): RawAssessmentJson {
  try {
    return JSON.parse(s) as RawAssessmentJson;
  } catch {
    return {};
  }
}

/** The 81 narrative assessments carry a single free-text "Wound narrative". */
export function isNarrativeAssessment(f: AssessmentFields): boolean {
  return "Wound narrative" in f && !("Wound Type" in f);
}

export const narrativeAnswer = (f: AssessmentFields): string => f["Wound narrative"] ?? "";

const num = (v: string | undefined): number | null => {
  if (v == null) return null;
  const n = parseFloat(String(v).trim());
  return Number.isFinite(n) ? n : null;
};
const clean = (v: string | undefined): string | null => {
  const t = (v ?? "").trim();
  return t && !/^n\/?a$/i.test(t) ? t : null;
};

/** Parse the 219 structured assessments (labeled fields) into a ParsedSource. */
export function parseStructured(f: AssessmentFields): ParsedSource {
  const present = /^yes$/i.test(f["Drainage Present"] ?? "")
    ? true
    : /^no$/i.test(f["Drainage Present"] ?? "")
      ? false
      : null;
  const amount = present === false ? "none" : normalizeDrainageAmount(f["Drainage Amount"]);
  return {
    wounds: [
      {
        wound_type: normalizeWoundType(f["Wound Type"]),
        location: clean(f["Location"]),
        laterality: clean(f["Laterality"]),
        stage: normalizeStage(f["Stage"]),
        length_cm: num(f["Length (cm)"]),
        width_cm: num(f["Width (cm)"]),
        depth_cm: num(f["Depth (cm)"]),
      },
    ],
    drainage_present: present,
    drainage_type: normalizeDrainageType(f["Drainage Type"]),
    drainage_amount: amount,
  };
}
