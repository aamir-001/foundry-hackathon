import json, re
from collections import Counter

data = json.load(open("/Users/adithyahnair/Downloads/abi-hackathon/all_patient_data.json"))

note_types = Counter()
payer_types = Counter()
payer_codes = Counter()
assess_status = Counter()
assess_types = Counter()
raw_json_shapes = Counter()
clin_status = Counter()

n_no_notes = n_no_assess = n_no_dx = n_no_cov = 0
null_fields = Counter()

for rec in data:
    p = rec["patient"]
    for fld in ("first_name","last_name","birth_date","gender","primary_payer_code"):
        if p.get(fld) in (None, ""):
            null_fields[fld] += 1

    dx = rec["diagnoses"]; cov = rec["coverage"]; notes = rec["notes"]; assess = rec["assessments"]
    if not dx: n_no_dx += 1
    if not cov: n_no_cov += 1
    if not notes: n_no_notes += 1
    if not assess: n_no_assess += 1

    for d in dx:
        clin_status[d.get("clinical_status")] += 1
    for c in cov:
        payer_types[c.get("payer_type")] += 1
        payer_codes[c.get("payer_code")] += 1
    for n in notes:
        note_types[n.get("note_type")] += 1
    for a in assess:
        assess_status[a.get("status")] += 1
        assess_types[a.get("assessment_type")] += 1
        rj = a.get("raw_json")
        if rj:
            try:
                obj = json.loads(rj)
                keys = tuple(sorted(obj.keys()))
                # bucket by shape signature
                if "sections" in obj: raw_json_shapes["nested:sections/questions"] += 1
                elif "length_cm" in obj or "width_cm" in obj: raw_json_shapes["flat:length_cm/width_cm"] += 1
                elif "wound_narrative" in obj or "narrative" in obj: raw_json_shapes["narrative-field"] += 1
                else: raw_json_shapes["other:" + ",".join(keys[:5])] += 1
            except Exception as e:
                raw_json_shapes["UNPARSEABLE"] += 1

def show(title, c):
    print(f"\n== {title} ==")
    for k, v in c.most_common():
        print(f"  {v:>4}  {k}")

print("Total patients:", len(data))
print(f"No diagnoses: {n_no_dx} | No coverage: {n_no_cov} | No notes: {n_no_notes} | No assessments: {n_no_assess}")
show("Null demographic fields", null_fields)
show("Diagnosis clinical_status", clin_status)
show("Coverage payer_code", payer_codes)
show("Coverage payer_type", payer_types)
show("Note types", note_types)
show("Assessment status", assess_status)
show("Assessment types", assess_types)
show("raw_json shapes", raw_json_shapes)
