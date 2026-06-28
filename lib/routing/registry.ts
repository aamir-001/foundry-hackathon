import type { Extracted } from "@/lib/extract/types";

// Config-driven field registry (BUILD_PLAN §10). Extraction, recovery, and
// scoring all iterate this — new missing-field patterns at scale = new rows,
// not new code. Hard weights from §9 (each ≥12 → any one drops below the 90
// auto cutoff). present/recovered count as documented; suggested/unavailable
// keep the deduction.

export interface FieldDef {
  field: string;
  criterion: 1 | 2 | 3 | null;
  weight: number;
  obtainable: boolean; // a provider can supply it → 'unavailable' vs a hard block
  appliesTo?: (e: Extracted) => boolean; // conditional requirement (e.g. stage)
  label: string;
}

export const REGISTRY: FieldDef[] = [
  { field: "wound_type", criterion: 1, weight: 20, obtainable: false, label: "wound type" },
  { field: "measures", criterion: 3, weight: 20, obtainable: true, label: "length/width" },
  { field: "depth_cm", criterion: 3, weight: 25, obtainable: true, label: "depth" },
  { field: "drainage_amount", criterion: 3, weight: 18, obtainable: true, label: "drainage amount" },
  {
    field: "stage",
    criterion: 3,
    weight: 15,
    obtainable: true,
    appliesTo: (e) => e.wound_type === "pressure ulcer",
    label: "stage (pressure ulcer)",
  },
  { field: "location", criterion: null, weight: 12, obtainable: true, label: "location" },
  { field: "wound_dx_code", criterion: null, weight: 20, obtainable: true, label: "codeable wound dx" },
];

// Signal deductions (conflicts / ambiguity — not a single missing field).
export interface SignalDef {
  signal: "laterality_conflict" | "drainage_presence_conflict" | "multi_wound";
  weight: number;
  label: string;
}

export const SIGNALS: SignalDef[] = [
  { signal: "laterality_conflict", weight: 20, label: "laterality conflict" },
  { signal: "drainage_presence_conflict", weight: 18, label: "drainage presence conflict" },
  { signal: "multi_wound", weight: 15, label: "multi-wound (primary ambiguous)" },
];

// Advisory-only (0 weight): the data shows these are real / non-billable /
// already recovered, so deducting would wrongly flag ~30 clean patients (§9).
export const SOFT_SIGNALS = [
  "size_outlier",
  "depth_outlier",
  "drainage_type_conflict",
  "tissue_pct",
  "garbled_location",
] as const;

export const AUTO_CUTOFF = 90;
