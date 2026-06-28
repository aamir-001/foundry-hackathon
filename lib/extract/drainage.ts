import type { DrainageAmount } from "@/lib/extract/types";

// Drainage-amount normalization (BUILD_PLAN §7). The map MUST include the literal
// "light" and the shorthand vocabulary; "none" is checked first so "serous, none"
// resolves to none rather than a type-only match.
const RULES: [RegExp, DrainageAmount][] = [
  [/\b(none|no drainage|no exudate|dry)\b/i, "none"],
  [/\b(light|min|minimal|slight|scant|small|trace)\b/i, "light"],
  [/\b(mod|moderate)\b/i, "moderate"],
  [/\b(heavy|large|copious)\b/i, "heavy"],
];

export function normalizeDrainageAmount(
  s: string | null | undefined,
): DrainageAmount | null {
  if (!s) return null;
  for (const [re, val] of RULES) if (re.test(s)) return val;
  return null;
}

const TYPE_RE = /(serosanguineous|serosang\w*|serous|sanguineous|purulent|serous)/i;

export function normalizeDrainageType(s: string | null | undefined): string | null {
  if (!s) return null;
  const m = TYPE_RE.exec(s);
  if (!m) return null;
  const t = m[1].toLowerCase();
  return /^serosang/.test(t) ? "serosanguineous" : t;
}

/**
 * Pull a drainage amount from free text, preferring a "Drainage: ..." label,
 * then an adjective adjacent to a drainage cue ("Min drainage", "Mod serosang").
 */
export function drainageAmountFromText(t: string): DrainageAmount | null {
  const label = /drainage\s*[:\-]?\s*([^./\n]+)/i.exec(t);
  if (label) {
    const a = normalizeDrainageAmount(label[1]);
    if (a) return a;
  }
  const pre =
    /\b(none|no|light|min|minimal|slight|scant|small|trace|mod|moderate|heavy|large|copious)\b[\w\s,]{0,20}?(?:drainage|serosang\w*|serous|exudate)/i.exec(
      t,
    );
  if (pre) {
    const a = normalizeDrainageAmount(pre[1]);
    if (a) return a;
  }
  return null;
}
