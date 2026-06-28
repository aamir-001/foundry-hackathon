import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import type { PatientBundle } from "@/lib/pcc/types";
import { extractPatient } from "@/lib/extract/reconcile";
import { findMeasurements, normalizeWoundType } from "@/lib/extract/patterns";
import { normalizeDrainageAmount } from "@/lib/extract/drainage";

const sample = (id: string): PatientBundle =>
  JSON.parse(readFileSync(join(process.cwd(), "fixtures", "samples", `${id}.json`), "utf8"));

describe("FA-001 — narrative assessment, true depth gap", () => {
  const e = extractPatient(sample("FA-001"));
  it("is parsed from the narrative format", () => {
    expect(e.assessment_format).toBe("narrative");
  });
  it("extracts type, location, L and W", () => {
    expect(e.wound_type).toBe("pressure ulcer");
    expect(e.location).toMatch(/right hip/i);
    expect(e.length_cm).toBeCloseTo(2.9);
    expect(e.width_cm).toBeCloseTo(2.8);
  });
  it("has NO depth anywhere (the depth gap)", () => {
    expect(e.depth_cm).toBeNull();
  });
  it("captures stage and heavy drainage", () => {
    expect(e.stage).toBe("stage 3");
    expect(e.drainage_amount).toBe("heavy");
  });
});

describe("FA-002 — structured assessment, multi-wound, stage N/A", () => {
  const e = extractPatient(sample("FA-002"));
  it("is parsed from the structured format", () => {
    expect(e.assessment_format).toBe("structured");
  });
  it("extracts the primary wound L/W/D from structured fields", () => {
    expect(e.wound_type).toBe("pressure ulcer");
    expect(e.length_cm).toBeCloseTo(5.9);
    expect(e.width_cm).toBeCloseTo(4.5);
    expect(e.depth_cm).toBeCloseTo(1.8);
  });
  it("treats stage N/A as no stage", () => {
    expect(e.stage).toBeNull();
  });
  it("detects multi-wound (buttock + heel in the note)", () => {
    expect(e.is_multi_wound).toBe(true);
  });
});

describe("parser must-haves", () => {
  it("allows cm between dims (2.9 cm x 2.8)", () => {
    const m = findMeasurements("Measures 2.9 cm x 2.8 cm");
    expect(m).toHaveLength(1);
    expect(m[0].length_cm).toBeCloseTo(2.9);
    expect(m[0].width_cm).toBeCloseTo(2.8);
    expect(m[0].depth_cm).toBeNull();
  });
  it("parses 3-D with cm at the end and a trailing separate depth", () => {
    const m = findMeasurements("5.9 x 4.5cm, depth 1.8cm");
    expect(m[0].depth_cm).toBeCloseTo(1.8);
  });
  it("handles two wounds with one separate depth each", () => {
    const m = findMeasurements("5.9 x 4.5cm, depth 1.8cm. L heel 3.5x2.7, 0.9cm deep");
    expect(m).toHaveLength(2);
    expect(m[0].depth_cm).toBeCloseTo(1.8);
    expect(m[1].length_cm).toBeCloseTo(3.5);
    expect(m[1].depth_cm).toBeCloseTo(0.9);
  });
  it("dedupes 'diabetic diabetic' and maps to a canonical type", () => {
    expect(normalizeWoundType("Diabetic diabetic Right plantar")).toBe("diabetic foot ulcer");
  });
  it("drainage map includes the literal 'light' and shorthand", () => {
    expect(normalizeDrainageAmount("Min drainage")).toBe("light");
    expect(normalizeDrainageAmount("slight serous")).toBe("light");
    expect(normalizeDrainageAmount("serous, none")).toBe("none");
    expect(normalizeDrainageAmount("Mod serosang")).toBe("moderate");
  });
});
