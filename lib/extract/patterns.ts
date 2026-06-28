// Shared deterministic parsers: wound type, stage, laterality, measurements,
// location. Used by both structured.ts and narrative.ts. NO LLM (BUILD_PLAN §7).

// ── Wound type (all 7 README types; SSI matches its abbreviation) ──
const TYPE_RULES: [RegExp, string][] = [
  [/diabetic foot|\bdfu\b|\bdiabetic\b/i, "diabetic foot ulcer"],
  [/pressure (?:ulcer|injury)|\bpressure\b|decubitus/i, "pressure ulcer"],
  [/venous|stasis/i, "venous stasis ulcer"],
  [/arterial|ischemic/i, "arterial ulcer"],
  [/surgical site infection|surgical site|\bSSI\b|\bsurgical\b|post[- ]?op/i, "surgical site infection"],
  [/abscess/i, "abscess"],
  [/\bburns?\b/i, "burn"],
];

/** Strip `aprx`, collapse `diabetic diabetic`, then map to a canonical type. */
export function normalizeWoundType(s: string | null | undefined): string | null {
  if (!s) return null;
  const t = dedupeDiabetic(String(s)).replace(/\baprx\b/gi, " ").trim();
  for (const [re, val] of TYPE_RULES) if (re.test(t)) return val;
  return null;
}

export function dedupeDiabetic(s: string): string {
  return s.replace(/\b(diabetic)(\s+\1\b)+/gi, "$1");
}

// ── Stage (pressure ulcers) ──
export function normalizeStage(s: string | null | undefined): string | null {
  if (!s) return null;
  const t = String(s).trim();
  if (!t || /^n\/?a$/i.test(t)) return null;
  if (/unstageable/i.test(t)) return "unstageable";
  const m = /stage\s*([1-4])/i.exec(t) ?? /^\s*([1-4])\s*$/.exec(t);
  return m ? `stage ${m[1]}` : null;
}

/** Stage embedded in free text ("Stage: Stage 3", "unstageable"). */
export function stageFromText(t: string): string | null {
  if (/unstageable/i.test(t)) return "unstageable";
  const m = /stage[:\s]*([1-4])/i.exec(t);
  return m ? `stage ${m[1]}` : null;
}

// ── Laterality ──
export function parseLaterality(s: string | null | undefined): string | null {
  if (!s) return null;
  if (/\bbilateral\b/i.test(s)) return "Bilateral";
  if (/\bright\b/i.test(s)) return "Right";
  if (/\bleft\b/i.test(s)) return "Left";
  return null;
}

// ── Measurements (the parser must-have: optional `cm` between dims) ──
const MEAS_RE =
  /(\d+(?:\.\d+)?)\s*(?:cm)?\s*[x×]\s*(\d+(?:\.\d+)?)(?:\s*(?:cm)?\s*[x×]\s*(\d+(?:\.\d+)?))?\s*(?:cm)?/gi;
const DEPTH_RE = /(?:depth\s*(\d+(?:\.\d+)?)\s*cm)|(?:(\d+(?:\.\d+)?)\s*cm\s*deep)/gi;

export interface Measurement {
  length_cm: number;
  width_cm: number;
  depth_cm: number | null;
  index: number; // position in the source text (for multi-wound ordering)
}

/** All L×W(×D) measurements in a text; separate "depth N cm"/"N cm deep" tokens
 *  are attached to the measurement whose span they fall within. */
export function findMeasurements(text: string): Measurement[] {
  const out: Measurement[] = [];
  let m: RegExpExecArray | null;
  MEAS_RE.lastIndex = 0;
  while ((m = MEAS_RE.exec(text))) {
    out.push({
      length_cm: parseFloat(m[1]),
      width_cm: parseFloat(m[2]),
      depth_cm: m[3] != null ? parseFloat(m[3]) : null,
      index: m.index,
    });
  }
  const depths: { val: number; index: number }[] = [];
  let d: RegExpExecArray | null;
  DEPTH_RE.lastIndex = 0;
  while ((d = DEPTH_RE.exec(text))) {
    depths.push({ val: parseFloat(d[1] ?? d[2]), index: d.index });
  }
  for (let i = 0; i < out.length; i++) {
    if (out[i].depth_cm != null) continue;
    const start = out[i].index;
    const end = i + 1 < out.length ? out[i + 1].index : Infinity;
    const cand = depths.find((dp) => dp.index >= start && dp.index < end);
    if (cand) out[i].depth_cm = cand.val;
  }
  return out;
}

// ── Location ──
const tidy = (s: string) => s.replace(/\s+/g, " ").trim();

/** Parse a wound location from narrative/notes ("…to Right hip", "<type> Left
 *  buttock measures", "Wound note - Rightlowerle."). */
export function parseLocation(t: string): string | null {
  let m =
    /\bto\s+((?:left|right|bilateral)?\s*[a-z][a-z ]*?)\s*(?:\/|,|\.|measures|measuring|stage|drainage|$)/i.exec(
      t,
    );
  if (m && m[1].trim()) return tidy(m[1]);
  m =
    /(?:ulcer|venous|diabetic|arterial|abscess|burn|infection|wound)\s+((?:left|right|bilateral)\s+[a-z][a-z ]*?)\s+(?:measures|measuring|meas\b)/i.exec(
      t,
    );
  if (m && m[1].trim()) return tidy(m[1]);
  m = /wound note\s*-\s*([a-z]+)\b/i.exec(t);
  if (m) return tidy(m[1]);
  return null;
}
