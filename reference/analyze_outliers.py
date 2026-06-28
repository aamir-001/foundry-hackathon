#!/usr/bin/env python3
"""Detect outliers and messy/conflicting data across all 300 patients.

Reads all_patient_data.json and writes a delineated report: outliers_report.txt
Categories:
  A. Billing eligibility   (payer / coverage problems)
  B. Diagnosis             (no active wound dx, etc.)
  C. Measurement complete  (missing depth/dims, stage N/A on pressure ulcer)
  D. Multi-wound ambiguity (note describes 2+ wounds)
  E. Cross-source conflict (note vs assessment disagree)
  F. Internal data quality (impossible tissue %, drainage contradictions,
                            garbled location strings, implausible values)
  G. Statistical outliers  (wound size / depth far from the population)
"""
import json
import re
import statistics
from collections import defaultdict

DATA = "/Users/adithyahnair/Downloads/abi-hackathon/all_patient_data.json"
OUT = "/Users/adithyahnair/Downloads/abi-hackathon/outliers_report.txt"

WOUND_ICD_PREFIXES = ("L89", "L97", "L98", "I83", "I70", "T81", "L02", "T2")
DRAINAGE_CANON = {
    "serosang": "serosanguineous", "serosanguineous": "serosanguineous",
    "serous": "serous", "sanguineous": "sanguineous",
    "purulent": "purulent", "none": "none",
}
KNOWN_LOCATION_WORDS = {
    "sacrum","sacral","heel","buttock","plantar","hip","ankle","coccyx","trochanter",
    "ischium","ischial","cervical","abdominal","lower","leg","foot","toe","elbow",
    "shoulder","back","thigh","knee","calf","forearm","wall"
}


def load():
    return json.load(open(DATA))


RE_NARR_MEAS = re.compile(r"Measures?\s*(\d+\.?\d*)\s*cm\s*[xX]\s*(\d+\.?\d*)\s*cm(?:\s*[xX]\s*(\d+\.?\d*))?", re.I)


def parse_assessment(a):
    """Flatten an assessment raw_json into a normalized field dict.

    Handles BOTH sub-schemas:
      * labeled fields  -> questions like 'Length (cm)', 'Drainage Type', ...
      * wound narrative -> single free-text answer needing NLP (2-D, no depth)
    Sets out['_schema'] to 'labeled' | 'narrative' | 'unparseable'.
    """
    out = {}
    rj = a.get("raw_json")
    if not rj:
        out["_schema"] = "empty"
        return out
    try:
        obj = json.loads(rj)
    except Exception:
        out["_schema"] = "unparseable"
        return out
    raw = {}
    for s in obj.get("sections", []):
        for q in s.get("questions", []):
            raw[(q.get("question") or "").strip()] = q.get("answer")

    if "Length (cm)" in raw:
        out.update(raw)
        out["_schema"] = "labeled"
        return out

    # narrative sub-schema: parse the free-text answer
    out["_schema"] = "narrative"
    narrative = next((v for k, v in raw.items() if "narrative" in k.lower()), "") or ""
    out["_narrative"] = narrative
    # "WoundType to Location / Measures X cm x Y cm / Stage: S / Drainage: type, amount"
    m = re.match(r"\s*(.+?)\s+to\s+(.+?)\s*/", narrative)
    if m:
        out["Wound Type"] = m.group(1).strip()
        out["Location"] = m.group(2).strip()
    mm = RE_NARR_MEAS.search(narrative)
    if mm:
        out["Length (cm)"] = mm.group(1)
        out["Width (cm)"] = mm.group(2)
        out["Depth (cm)"] = mm.group(3)  # usually None (2-D only)
    ms = re.search(r"Stage:\s*([^/]+)", narrative)
    if ms:
        out["Stage"] = ms.group(1).strip()
    md = re.search(r"Drainage:\s*([A-Za-z]+),?\s*([A-Za-z]+)?", narrative)
    if md:
        out["Drainage Type"] = md.group(1).strip()
        if md.group(2):
            out["Drainage Amount"] = md.group(2).strip()
    return out


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def canon_drainage(text):
    if not text:
        return None
    t = text.lower()
    for k, v in DRAINAGE_CANON.items():
        if k in t:
            return v
    return None


# measurement patterns from note free-text
RE_3D = re.compile(r"(\d+\.?\d*)\s*[xX]\s*(\d+\.?\d*)\s*[xX]\s*(\d+\.?\d*)")
RE_2D = re.compile(r"(\d+\.?\d*)\s*cm\s*[xX]\s*(\d+\.?\d*)\s*cm")
RE_2D_PLAIN = re.compile(r"(\d+\.?\d*)\s*[xX]\s*(\d+\.?\d*)")
RE_DEPTH = re.compile(r"depth\s*(\d+\.?\d*)", re.I)


def parse_note_measurements(text):
    """Return list of (L,W,D) tuples found (D may be None). First = primary."""
    if not text:
        return []
    results = []
    for m in RE_3D.finditer(text):
        results.append((num(m.group(1)), num(m.group(2)), num(m.group(3))))
    if results:
        return results
    # 2-D with explicit cm (Envive)
    for m in RE_2D.finditer(text):
        results.append((num(m.group(1)), num(m.group(2)), None))
    # plain 2-D plus a separate "depth X"
    if not results:
        for m in RE_2D_PLAIN.finditer(text):
            results.append((num(m.group(1)), num(m.group(2)), None))
        depths = RE_DEPTH.findall(text)
        if results and depths:
            l, w, _ = results[0]
            results[0] = (l, w, num(depths[0]))
    return results


def main():
    data = load()
    flags = defaultdict(list)   # category -> list of (patient_id, message)

    # population stats for statistical outliers
    areas, depths, lengths, widths = [], [], [], []
    for rec in data:
        for a in rec["assessments"]:
            f = parse_assessment(a)
            L, W, D = num(f.get("Length (cm)")), num(f.get("Width (cm)")), num(f.get("Depth (cm)"))
            if L and W:
                areas.append(L * W)
                lengths.append(L); widths.append(W)
            if D is not None:
                depths.append(D)

    def bounds(vals):
        if len(vals) < 4:
            return (None, None)
        q = statistics.quantiles(vals, n=4)
        iqr = q[2] - q[0]
        return (q[0] - 1.5 * iqr, q[2] + 1.5 * iqr)

    area_lo, area_hi = bounds(areas)
    depth_lo, depth_hi = bounds(depths)

    for rec in data:
        p = rec["patient"]
        pid = p["patient_id"]
        dx, cov, notes, assess = rec["diagnoses"], rec["coverage"], rec["notes"], rec["assessments"]

        # ---------- A. Billing eligibility ----------
        primary = p.get("primary_payer_code")
        cov_codes = [c.get("payer_code") for c in cov]
        active_mcb = any(c.get("payer_code") == "MCB" and not c.get("effective_to") for c in cov)
        expired_mcb = [c for c in cov if c.get("payer_code") == "MCB" and c.get("effective_to")]
        if primary == "MCB" and not active_mcb:
            flags["A"].append((pid, f"primary_payer_code=MCB but NO active MCB coverage (codes={cov_codes})"))
        if primary not in cov_codes:
            flags["A"].append((pid, f"primary_payer_code={primary} not present in coverage records {cov_codes}"))
        if expired_mcb:
            for c in expired_mcb:
                flags["A"].append((pid, f"MCB coverage TERMINATED on {c.get('effective_to')}"))
        # payer_type uninformative
        ptypes = {c.get("payer_type") for c in cov}
        if "Medicare" in ptypes and len(cov) and all(c.get("payer_type") == "Medicare" for c in cov if c.get("payer_code") in ("MCB","MCA","MCD")):
            pass  # systemic, reported once in summary

        # ---------- B. Diagnosis ----------
        wound_dx = [d for d in dx if (d.get("icd10_code") or "").upper().startswith(WOUND_ICD_PREFIXES)]
        active_wound_dx = [d for d in wound_dx if d.get("clinical_status") == "active"]
        if not wound_dx:
            flags["B"].append((pid, f"NO wound-type ICD-10 diagnosis at all (codes={[d.get('icd10_code') for d in dx]})"))
        elif not active_wound_dx:
            flags["B"].append((pid, f"wound dx present but NONE active (all resolved/inactive)"))

        # ---------- assessment fields (primary, clean source) ----------
        af = parse_assessment(assess[0]) if assess else {}
        aL, aW, aD = num(af.get("Length (cm)")), num(af.get("Width (cm)")), num(af.get("Depth (cm)"))
        a_wtype = (af.get("Wound Type") or "").strip()
        a_stage = (af.get("Stage") or "").strip()
        a_loc = (af.get("Location") or "").strip()
        a_lat = (af.get("Laterality") or "").strip()
        a_drain_present = (af.get("Drainage Present") or "").strip()
        a_drain_type = canon_drainage(af.get("Drainage Type"))
        a_drain_amt = (af.get("Drainage Amount") or "").strip()
        gran = num(af.get("Granulation %"))
        slough = num(af.get("Slough %"))

        # ---------- C. Measurement completeness ----------
        a_schema = af.get("_schema")
        if assess:
            if a_schema == "narrative":
                # measurements live in free text and are 2-D only (no depth)
                flags["C"].append((pid, f"assessment is FREE-TEXT narrative (not labeled fields); needs NLP, 2-D only L={aL} W={aW}, no depth"))
            elif aL is None or aW is None or aD is None:
                miss = [n for n, v in (("L", aL), ("W", aW), ("D", aD)) if v is None]
                flags["C"].append((pid, f"assessment missing dimension(s): {','.join(miss)} (L={aL} W={aW} D={aD})"))
            if "pressure" in a_wtype.lower() and (not a_stage or a_stage.upper() in ("N/A", "NA", "")):
                flags["C"].append((pid, f"pressure ulcer with Stage='{a_stage}' (missing/ungradable stage)"))

        # ---------- note parsing (primary = latest by effective_date) ----------
        primary_note = max(notes, key=lambda n: n.get("effective_date") or "") if notes else None
        ntext = primary_note.get("note_text") if primary_note else ""
        nmeas = parse_note_measurements(ntext)
        is_envive = "*Envive Care Conference Review" in (ntext or "")

        # depth available anywhere for this patient? (notes + assessment)
        depth_anywhere = aD is not None
        for n in notes:
            for (_l, _w, _d) in parse_note_measurements(n.get("note_text")):
                if _d is not None:
                    depth_anywhere = True

        # ---------- C (depth gaps) ----------
        if primary_note and nmeas and nmeas[0][2] is None:
            L0, W0, _ = nmeas[0]
            if not depth_anywhere:
                flags["C"].append((pid, f"NO depth anywhere (note {L0}x{W0}cm 2-D, assessment depth missing too) — true gap"))
            else:
                flags["C"].append((pid, f"primary note is 2-D only ({L0}x{W0}cm" + (", Envive" if is_envive else "") + "); depth recoverable from assessment/sibling note"))

        # ---------- D. Multi-wound ----------
        multiword_markers = ("also eval", "both wounds", "second wound", "wound also")
        if primary_note and (len(nmeas) >= 2 or any(m in (ntext or "").lower() for m in multiword_markers)):
            flags["D"].append((pid, f"note describes MULTIPLE wounds ({len(nmeas)} measurement sets) — primary ambiguous"))

        # ---------- E. Cross-source conflicts (note vs assessment) ----------
        if primary_note and nmeas and aL and aW:
            L0, W0, D0 = nmeas[0]
            def diff(a, b):
                return a is not None and b is not None and abs(a - b) > 0.25
            if diff(L0, aL) or diff(W0, aW):
                flags["E"].append((pid, f"L/W mismatch: note {L0}x{W0} vs assessment {aL}x{aW}"))
            if D0 is not None and aD is not None and abs(D0 - aD) > 0.25:
                flags["E"].append((pid, f"depth mismatch: note {D0} vs assessment {aD}"))
        # drainage type conflict
        n_drain = canon_drainage(ntext)
        if n_drain and a_drain_type and n_drain != a_drain_type:
            flags["E"].append((pid, f"drainage type conflict: note='{n_drain}' vs assessment='{a_drain_type}'"))
        # laterality vs location side
        loc_l = a_loc.lower()
        if a_lat in ("Left", "Right") and (("left" in loc_l) or ("right" in loc_l)):
            loc_side = "Left" if "left" in loc_l else "Right"
            if loc_side != a_lat:
                flags["E"].append((pid, f"laterality '{a_lat}' contradicts location '{a_loc}'"))
        # wound type: note vs assessment
        for wt in ("pressure", "diabetic", "surgical", "abscess", "venous", "arterial", "burn"):
            if a_wtype and wt in a_wtype.lower() and ntext and wt not in ntext.lower():
                # only flag if note clearly names a different known type
                note_types_found = [w for w in ("pressure","diabetic","surgical","abscess","venous","arterial","burn") if w in ntext.lower()]
                if note_types_found and wt not in note_types_found:
                    flags["E"].append((pid, f"wound type conflict: assessment='{a_wtype}' vs note mentions {note_types_found}"))
                break

        # ---------- F. Internal data quality ----------
        if gran is not None and slough is not None:
            tot = gran + slough
            if tot > 100:
                flags["F"].append((pid, f"tissue % impossible: granulation {gran}% + slough {slough}% = {tot}% (>100)"))
            elif tot < 90:
                flags["F"].append((pid, f"tissue % under-accounts: granulation {gran}% + slough {slough}% = {tot}%"))
        if a_drain_present.lower() == "no" and a_drain_type and a_drain_type != "none":
            flags["F"].append((pid, f"contradiction: Drainage Present=No but Drainage Type='{a_drain_type}'"))
        if a_drain_present.lower() == "yes" and a_drain_amt.lower() == "none":
            flags["F"].append((pid, f"contradiction: Drainage Present=Yes but Drainage Amount=None"))
        if is_envive and "none" in (ntext or "").lower() and "present" in (ntext or "").lower():
            if re.search(r"present\s*-\s*\w+,\s*none", ntext, re.I):
                flags["F"].append((pid, f"Envive note: 'Drainage present ... none' contradiction"))
        # garbled location string in note (e.g. 'Rightplantar', 'Rightcervica')
        m = re.search(r"Wound note\s*-\s*([A-Za-z]+)\.", ntext or "")
        if m:
            locword = m.group(1)
            low = locword.lower()
            joined = (low.startswith("left") and len(low) > 4) or (low.startswith("right") and len(low) > 5)
            tail = low[4:] if low.startswith("left") else (low[5:] if low.startswith("right") else low)
            if joined and tail not in KNOWN_LOCATION_WORDS:
                flags["F"].append((pid, f"garbled/truncated location in note: '{locword}'"))
        # implausible measurement values
        for src, (L, W, D) in (("assessment", (aL, aW, aD)),):
            if L and L > 25: flags["F"].append((pid, f"{src} length implausibly large: {L} cm"))
            if W and W > 25: flags["F"].append((pid, f"{src} width implausibly large: {W} cm"))
            if D is not None and D > 10: flags["F"].append((pid, f"{src} depth implausibly large: {D} cm"))
            if L == 0 or W == 0: flags["F"].append((pid, f"{src} has zero dimension (L={L} W={W})"))

        # ---------- G. Statistical outliers ----------
        if aL and aW:
            area = aL * aW
            if area_hi and area > area_hi:
                flags["G"].append((pid, f"wound area {area:.1f} cm² is a high outlier (pop. upper fence {area_hi:.1f})"))
        if aD is not None and depth_hi and aD > depth_hi:
            flags["G"].append((pid, f"wound depth {aD} cm is a high outlier (pop. upper fence {depth_hi:.1f})"))

    write_report(data, flags, dict(areas=areas, depths=depths))
    # console summary
    cats = {
        "A": "Billing eligibility / coverage",
        "B": "Diagnosis problems",
        "C": "Measurement completeness",
        "D": "Multi-wound ambiguity",
        "E": "Cross-source conflicts (note vs assessment)",
        "F": "Internal data-quality outliers",
        "G": "Statistical size/depth outliers",
    }
    print("OUTLIER / MESSY-DATA SUMMARY")
    print("=" * 50)
    total = 0
    for c in "ABCDEFG":
        n = len(flags[c])
        total += n
        print(f"  [{c}] {cats[c]:<45} {n:>4}")
    print(f"  {'TOTAL flags':<49} {total:>4}")
    affected = {pid for lst in flags.values() for pid, _ in lst}
    print(f"  Patients with >=1 flag: {len(affected)} / {len(data)}")
    print(f"\nFull report: {OUT}")


def write_report(data, flags, stats):
    cats = {
        "A": "BILLING ELIGIBILITY / COVERAGE PROBLEMS",
        "B": "DIAGNOSIS PROBLEMS (no active wound dx, etc.)",
        "C": "MEASUREMENT COMPLETENESS (missing depth / dims / stage)",
        "D": "MULTI-WOUND AMBIGUITY (which wound is primary?)",
        "E": "CROSS-SOURCE CONFLICTS (progress note vs assessment)",
        "F": "INTERNAL DATA-QUALITY OUTLIERS (impossible/garbled values)",
        "G": "STATISTICAL OUTLIERS (wound size / depth)",
    }
    by_patient = defaultdict(lambda: defaultdict(list))
    for c, lst in flags.items():
        for pid, msg in lst:
            by_patient[pid][c].append(msg)

    lines = []
    lines.append("=" * 80)
    lines.append("ABI HACKATHON — OUTLIERS & MESSY-DATA REPORT")
    lines.append(f"Patients analyzed : {len(data)}")
    total = sum(len(v) for v in flags.values())
    affected = {pid for lst in flags.values() for pid, _ in lst}
    lines.append(f"Total flags       : {total}")
    lines.append(f"Patients affected : {len(affected)} / {len(data)}")
    lines.append("=" * 80)
    lines.append("")
    schema_counts = defaultdict(int)
    for rec in data:
        if rec["assessments"]:
            schema_counts[parse_assessment(rec["assessments"][0]).get("_schema")] += 1
    lines.append("SYSTEMIC ISSUES (affect the whole dataset):")
    lines.append("  * payer_type is collapsed to 'Medicare' for MCB/MCA/MCD alike —")
    lines.append("    you CANNOT distinguish Part B from Part A via payer_type; use payer_code.")
    lines.append("  * Documented flat raw_json schema (length_cm, width_cm...) is NEVER used;")
    lines.append("    all 300 assessments nest data under sections[].questions[].answer.")
    lines.append(f"  * Assessment raw_json comes in TWO sub-schemas: "
                 f"{schema_counts.get('labeled',0)} 'labeled fields' (clean L/W/D) vs "
                 f"{schema_counts.get('narrative',0)} 'wound narrative' free-text")
    lines.append("    (2-D only, no depth — must be NLP-parsed just like Envive notes).")
    lines.append("  * note_type does NOT indicate format — Envive narratives appear under")
    lines.append("    'Wound (SPN)', 'HP Skin & Wound Note', 'Wound (IDT)', etc.")
    lines.append("  * Undocumented note types present: 'Wound (IDT)', 'Wound Care Progress Note'.")
    lines.append("  * 174/300 patients have TWO current progress notes (often one Envive 2-D +")
    lines.append("    one structured) — depth/details must be merged across notes.")
    lines.append("")

    lines.append("-" * 80)
    lines.append("SECTION 1 — FLAGS GROUPED BY CATEGORY")
    lines.append("-" * 80)
    for c in "ABCDEFG":
        lines.append("")
        lines.append(f"### [{c}] {cats[c]}  ({len(flags[c])} flags)")
        if not flags[c]:
            lines.append("    (none)")
            continue
        for pid, msg in sorted(flags[c]):
            lines.append(f"    {pid}: {msg}")

    lines.append("")
    lines.append("-" * 80)
    lines.append("SECTION 2 — FLAGS GROUPED BY PATIENT (only affected patients)")
    lines.append("-" * 80)
    for pid in sorted(by_patient):
        lines.append("")
        lines.append(f"#### {pid}")
        for c in "ABCDEFG":
            for msg in by_patient[pid][c]:
                lines.append(f"    [{c}] {msg}")

    with open(OUT, "w") as f:
        f.write("\n".join(lines))


if __name__ == "__main__":
    main()
