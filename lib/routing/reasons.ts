import type { ScoreResult } from "@/lib/routing/rules";

// Deterministic, plain-English reasons (BUILD_PLAN §9) — 0 LLM. The optional
// Haiku "Summarize" (Phase 5 /api/summarize) only rewrites this into prose.

export function buildReason(sr: ScoreResult): string {
  if (sr.routing_decision === "reject") return rejectReason(sr);
  if (sr.routing_decision === "auto_accept") return acceptReason(sr);
  return flagReason(sr);
}

function rejectReason(sr: ScoreResult): string {
  switch (sr.reject_reason) {
    case "not_medicare_b":
      return "Rejected — no active Medicare Part B coverage (criterion 2).";
    case "no_active_wound":
      return "Rejected — no active wound on record (criterion 1).";
    case "extraction_unreliable":
      return "Rejected — reliable extraction not possible: wound type/measurements could not be determined from any source (criterion 3).";
    default:
      return "Rejected.";
  }
}

function acceptReason(sr: ScoreResult): string {
  const e = sr.extracted;
  const dx = sr.recovery.field_status.wound_dx_code?.value;
  const dims = [e.length_cm, e.width_cm, e.depth_cm].filter((v) => v != null).join("×");
  return `Accepted — all 3 criteria met: ${e.wound_type ?? "wound"}${dx ? ` (${dx})` : ""}, Medicare Part B, measurements ${dims}cm + ${e.drainage_amount ?? "?"} drainage; no conflicts. Score 100.`;
}

function flagReason(sr: ScoreResult): string {
  const fs = sr.recovery.field_status;
  const items: string[] = [];

  // Notable recovery (positive context): depth filled from another source.
  const depth = fs.depth_cm;
  if (depth?.tier === "recovered") items.push(`depth recovered from ${depth.source} (${depth.value}cm)`);

  for (const d of sr.deductions) {
    switch (d.code) {
      case "depth_cm":
        items.push("depth not in record — request from provider");
        break;
      case "stage":
        items.push("stage not documented — request from provider");
        break;
      case "wound_dx_code":
        items.push(`no codeable wound dx — suggested ${sr.recovery.suggested_dx_code ?? "L-code"}`);
        break;
      case "location":
        items.push("location not in record — request from provider");
        break;
      case "measures":
        items.push("length/width not obtainable");
        break;
      case "wound_type":
        items.push("wound type indeterminate");
        break;
      case "drainage_amount":
        items.push("drainage amount not in record — request from provider");
        break;
      case "laterality_conflict":
        items.push(`laterality conflict — ${d.detail || "confirm side"}`);
        break;
      case "drainage_presence_conflict":
        items.push("drainage presence conflict (documented presence vs amount)");
        break;
      case "multi_wound":
        items.push(`multi-wound — suggested primary: ${sr.recovery.suggested_primary ?? "confirm"}`);
        break;
      default:
        items.push(d.label);
    }
  }

  const badges = sr.soft.length ? ` Advisory: ${sr.soft.join(", ")}.` : "";
  return `Eligible (active wound + Medicare Part B). Review: ${items.join("; ")}.${badges} Score ${sr.score}.`;
}
