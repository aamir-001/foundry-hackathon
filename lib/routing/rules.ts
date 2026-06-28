import type { PatientBundle } from "@/lib/pcc/types";
import type { Extracted, RecoveryResult, RecoveryTier } from "@/lib/extract/types";
import type { RejectReason, RoutingDecision } from "@/lib/supabase/types";
import { recoverPatient } from "@/lib/extract/recover";
import { flattenAssessment } from "@/lib/extract/structured";
import { AUTO_CUTOFF, REGISTRY, SIGNALS } from "@/lib/routing/registry";

export interface Deduction {
  code: string;
  label: string;
  weight: number;
  detail: string;
}

export interface ScoreResult {
  recovery: RecoveryResult;
  extracted: Extracted;
  has_active_wound: boolean;
  has_active_mcb: boolean;
  has_required_measures: boolean;
  has_wound_dx_code: boolean;
  routing_decision: RoutingDecision;
  score: number;
  reject_reason: RejectReason | null;
  deductions: Deduction[];
  soft: string[];
}

const documented = (tier: RecoveryTier | undefined): boolean =>
  tier === "present" || tier === "recovered";

const num = (x: unknown): number | null => {
  const n = parseFloat(String(x));
  return Number.isFinite(n) ? n : null;
};

// Population fences (BUILD_PLAN §2: area>29.6cm², depth>2.5cm are real outliers).
const AREA_FENCE = 29.6;
const DEPTH_FENCE = 2.5;

export function scorePatient(
  bundle: PatientBundle,
  billerInputs?: Record<string, unknown> | null,
): ScoreResult {
  const recovery = recoverPatient(bundle, billerInputs);
  const e = recovery.extracted;
  const fs = recovery.field_status;

  // ── eligibility (the 3 criteria) ──
  const has_active_mcb = bundle.coverage.some((c) => c.payer_code === "MCB" && !c.effective_to);
  const has_required_measures = e.length_cm != null && e.width_cm != null;
  const has_active_wound = e.wounds.length > 0 && (e.wound_type != null || has_required_measures);
  const extractable = e.wound_type != null && has_required_measures;

  // ── Step 1: reject gate ──
  let reject_reason: RejectReason | null = null;
  if (!has_active_wound) reject_reason = "no_active_wound";
  else if (!has_active_mcb) reject_reason = "not_medicare_b";
  else if (!extractable) reject_reason = "extraction_unreliable";

  const base = {
    recovery,
    extracted: e,
    has_active_wound,
    has_active_mcb,
    has_required_measures,
    has_wound_dx_code: recovery.has_wound_dx_code,
  };

  if (reject_reason) {
    return {
      ...base,
      routing_decision: "reject",
      score: 0,
      reject_reason,
      deductions: [],
      soft: [],
    };
  }

  // ── Step 2: score over the registry (eligible + extractable only) ──
  const deductions: Deduction[] = [];
  for (const def of REGISTRY) {
    if (def.appliesTo && !def.appliesTo(e)) continue;
    const ok = def.field === "measures" ? has_required_measures : documented(fs[def.field]?.tier);
    if (!ok) {
      deductions.push({
        code: def.field,
        label: def.label,
        weight: def.weight,
        detail: fs[def.field]?.source ?? "missing",
      });
    }
  }
  for (const sig of SIGNALS) {
    const on =
      sig.signal === "laterality_conflict"
        ? recovery.laterality_conflict
        : sig.signal === "drainage_presence_conflict"
          ? recovery.drainage_presence_conflict
          : e.is_multi_wound;
    if (on) {
      const detail =
        sig.signal === "multi_wound" ? (recovery.suggested_primary ?? "") : String(fs.laterality?.value ?? "");
      deductions.push({ code: sig.signal, label: sig.label, weight: sig.weight, detail });
    }
  }

  const score = Math.max(0, 100 - deductions.reduce((s, d) => s + d.weight, 0));
  const routing_decision: RoutingDecision =
    score >= AUTO_CUTOFF ? "auto_accept" : "flag_for_review";

  return { ...base, routing_decision, score, reject_reason: null, deductions, soft: softSignals(bundle, e, recovery) };
}

// Advisory badges (0 weight) — real/non-billable/recovered, never deducted.
function softSignals(bundle: PatientBundle, e: Extracted, r: RecoveryResult): string[] {
  const out: string[] = [];
  const f = flattenAssessment(bundle.assessments[0]?.raw_json);
  if (e.length_cm != null && e.width_cm != null && e.length_cm * e.width_cm > AREA_FENCE)
    out.push("size_outlier");
  if (e.depth_cm != null && e.depth_cm > DEPTH_FENCE) out.push("depth_outlier");
  const gran = num(f["Granulation %"]);
  const slough = num(f["Slough %"]);
  if (gran != null && slough != null && gran + slough !== 100) out.push("tissue_pct");
  if (r.field_status.location?.source?.includes("note")) out.push("garbled_location_recovered");
  return out;
}
