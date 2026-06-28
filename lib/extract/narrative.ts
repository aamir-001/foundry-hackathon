import type { ParsedSource, WoundMention } from "@/lib/extract/types";
import {
  normalizeWoundType,
  stageFromText,
  parseLaterality,
  parseLocation,
  findMeasurements,
  dedupeDiabetic,
} from "@/lib/extract/patterns";
import { drainageAmountFromText, normalizeDrainageType } from "@/lib/extract/drainage";

/**
 * Parse free text — the narrative assessment answer OR a progress note. Handles
 * the three note formats (Envive, prose-measures, prose-Meas), multi-wound
 * (multiple measurement sets), and the parser must-haves (cm between dims,
 * "…to <location>"). Returns ≥1 WoundMention.
 */
export function parseFreeText(text: string): ParsedSource {
  const t = dedupeDiabetic(text ?? "").replace(/\baprx\b/gi, " ");
  const meas = findMeasurements(t);
  const primaryType = normalizeWoundType(t);
  const primaryStage = stageFromText(t);
  const primaryLoc = parseLocation(t);

  const wounds: WoundMention[] = [];
  if (meas.length === 0) {
    wounds.push({
      wound_type: primaryType,
      location: primaryLoc,
      laterality: parseLaterality(primaryLoc ?? t),
      stage: primaryStage,
      length_cm: null,
      width_cm: null,
      depth_cm: null,
    });
  } else {
    meas.forEach((m, i) => {
      // For secondary wounds, look at the ~40 chars before the measurement for a
      // local location/type (e.g. "Heel wound also eval - L heel 3.5x2.7").
      const before = t.slice(Math.max(0, m.index - 45), m.index);
      const loc = i === 0 ? primaryLoc : (parseLocation(before) ?? localLocation(before));
      const type = i === 0 ? primaryType : (normalizeWoundType(before) ?? primaryType);
      wounds.push({
        wound_type: type,
        location: loc,
        laterality: parseLaterality(loc ?? "") ?? (i === 0 ? parseLaterality(t) : null),
        stage: i === 0 ? primaryStage : null,
        length_cm: m.length_cm,
        width_cm: m.width_cm,
        depth_cm: m.depth_cm,
      });
    });
  }

  const amount = drainageAmountFromText(t);
  return {
    wounds,
    drainage_present: amount == null ? null : amount !== "none",
    drainage_type: normalizeDrainageType(t),
    drainage_amount: amount,
  };
}

// Last-ditch local location for a secondary wound: a body word near the dims.
function localLocation(before: string): string | null {
  const m =
    /\b((?:left|right|l|r)\s+[a-z]+|heel|sacrum|sacral|hip|buttock|foot|ankle|leg|coccyx|trochanter)\b/i.exec(
      before,
    );
  return m ? m[0].replace(/\s+/g, " ").trim() : null;
}
