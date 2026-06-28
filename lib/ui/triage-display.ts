import type { TriageRow } from "@/lib/supabase/types";
import { FACILITY_NAME } from "@/lib/supabase/queries";

export type UiDecision = "accept" | "flag" | "reject";

const WOUND_TYPES = [
  "pressure ulcer",
  "diabetic foot ulcer",
  "venous stasis ulcer",
  "arterial ulcer",
  "surgical site infection",
  "abscess",
  "burn",
];

export function toUiDecision(d: TriageRow["routing_decision"]): UiDecision {
  if (d === "auto_accept") return "accept";
  if (d === "flag_for_review") return "flag";
  return "reject";
}

export function facilityLetter(facilityId: number | null): string {
  if (facilityId === 101) return "A";
  if (facilityId === 102) return "B";
  if (facilityId === 103) return "C";
  return "?";
}

export function patientName(r: TriageRow): string {
  return [r.first_name, r.last_name].filter(Boolean).join(" ") || r.patient_id;
}

export function sizeStr(r: TriageRow): string {
  const { length_cm: L, width_cm: W, depth_cm: D } = r;
  if (L == null || W == null) return "—";
  return D != null ? `${L}×${W}×${D} cm` : `${L}×${W} cm`;
}

export function woundTitle(r: TriageRow): string {
  if (!r.wound_type) return "No wound identified";
  return r.stage ? `Stage ${r.stage} ${titleCase(r.wound_type)}` : titleCase(r.wound_type);
}

export function woundSubtitle(r: TriageRow): string {
  if (!r.wound_type) return "Extraction failed";
  const loc = r.location ?? "—";
  const drain = r.drainage_amount ?? "—";
  return `${loc} · ${sizeStr(r)} · ${drain} drainage`;
}

export function confidencePct(r: TriageRow): number {
  if (r.confidence != null) return Math.round(r.confidence * 100);
  if (r.score != null) return r.score;
  return 0;
}

export function confBand(r: TriageRow): "high" | "med" | "low" {
  const p = confidencePct(r) / 100;
  if (p >= 0.85) return "high";
  if (p >= 0.7) return "med";
  return "low";
}

export function flagCategory(reason: string): string {
  const r = reason.toLowerCase();
  if (r.includes("medicare part b") && r.includes("not")) return "Coverage issue";
  if (r.includes("depth") && (r.includes("missing") || r.includes("unavailable"))) return "Missing depth";
  if (r.includes("no codeable") || r.includes("diagnosis")) return "No matching ICD-10";
  if (r.includes("multi-wound") || r.includes("multi wound")) return "Multi-wound";
  if (r.includes("laterality")) return "Laterality conflict";
  if (r.includes("suggested")) return "Suggested primary wound";
  if (r.includes("measurement") || r.includes("outlier")) return "Measurement concern";
  if (r.includes("drainage")) return "Drainage gap";
  return "Other review needed";
}

export function matchesSearch(r: TriageRow, q: string): boolean {
  const needle = q.trim().toLowerCase();
  if (!needle) return true;
  const hay = [
    r.patient_id,
    r.first_name,
    r.last_name,
    r.wound_type,
    r.location,
    r.reason,
    r.facility_id ? FACILITY_NAME[r.facility_id] : "",
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
  return hay.includes(needle);
}

export function matchesWoundFilter(r: TriageRow, wound: string): boolean {
  if (wound === "all") return true;
  return r.wound_type === wound;
}

export function matchesFacilityFilter(r: TriageRow, fac: string): boolean {
  if (fac === "all") return true;
  return facilityLetter(r.facility_id) === fac;
}

export function matchesConfFilter(r: TriageRow, band: string): boolean {
  if (band === "all") return true;
  const b = confBand(r);
  if (band === "high") return b === "high";
  if (band === "med") return b === "med";
  return b === "low";
}

export function severityScore(r: TriageRow): number {
  if (r.stage === "unstageable") return 3.5;
  const n = Number(r.stage);
  return Number.isFinite(n) ? n : 0;
}

/** Neutral sparkline when visit trend is unavailable. */
export function sparkPoints(r: TriageRow): string {
  const base = confidencePct(r) / 100;
  const ys = [0.55, 0.58, 0.6, 0.62, 0.64, base].map((v) => 18 - v * 14);
  return ys.map((y, i) => `${i * 12},${y.toFixed(1)}`).join(" ");
}

export function buildRules(r: TriageRow) {
  const rules: { s: "pass" | "warn" | "fail"; k: string; n: string }[] = [];
  rules.push({
    s: r.has_active_mcb ? "pass" : "fail",
    k: "Medicare Part B coverage",
    n: r.has_active_mcb ? "Active MCB on file" : "No active Medicare Part B (payer_code = MCB)",
  });
  rules.push({
    s: r.has_active_wound ? "pass" : "fail",
    k: "Active wound documented",
    n: r.has_active_wound ? (r.wound_type ?? "Wound documented") : "No active wound type identified",
  });
  rules.push({
    s: r.wound_type ? "pass" : "fail",
    k: "Wound type identified",
    n: r.wound_type ?? "Could not extract wound type",
  });
  const hasM = r.length_cm != null && r.width_cm != null;
  rules.push({
    s: hasM ? (r.depth_cm != null ? "pass" : "warn") : "fail",
    k: "Measurements documented",
    n: hasM ? (r.depth_cm != null ? sizeStr(r) : `${sizeStr(r)} · depth missing`) : "No L/W measurements",
  });
  rules.push({
    s: r.drainage_amount ? "pass" : "warn",
    k: "Drainage characterized",
    n: r.drainage_amount ?? "Not recorded",
  });
  rules.push({
    s: r.has_wound_dx_code ? "pass" : "fail",
    k: "Wound-related ICD-10 on file",
    n: r.has_wound_dx_code ? "Matching diagnosis present" : "No codeable wound diagnosis",
  });
  if (r.is_multi_wound) {
    rules.push({
      s: "warn",
      k: "Multi-wound documented",
      n: r.suggested_primary ? `Suggested primary: ${r.suggested_primary}` : "Confirm primary wound",
    });
  }
  return rules;
}

export { WOUND_TYPES };

function titleCase(s: string): string {
  return s.replace(/\b\w/g, (c) => c.toUpperCase());
}
