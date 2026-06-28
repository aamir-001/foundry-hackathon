import json, random
data = json.load(open("/Users/adithyahnair/Downloads/abi-hackathon/all_patient_data.json"))
random.seed(7)

print("########## SAMPLE NOTE TEXTS (varied) ##########")
samples = random.sample(data, 14)
for rec in samples:
    p = rec["patient"]
    for n in rec["notes"][:1]:
        print(f"\n--- {p['patient_id']} | note_type={n.get('note_type')!r} | by {n.get('created_by')} ---")
        print(repr(n.get("note_text"))[:600])

print("\n\n########## SAMPLE raw_json NARRATIVES ##########")
for rec in samples[:10]:
    p = rec["patient"]
    for a in rec["assessments"][:1]:
        rj = a.get("raw_json")
        try:
            obj = json.loads(rj)
            # extract narrative answers
            ans = []
            for s in obj.get("sections", []):
                for q in s.get("questions", []):
                    ans.append(f"[{q.get('question')}] {q.get('answer')}")
            print(f"\n--- {p['patient_id']} | {a.get('assessment_type')} | {a.get('status')} ---")
            for a2 in ans:
                print("   ", a2[:300])
        except Exception as e:
            print(f"\n--- {p['patient_id']} UNPARSEABLE: {e}")
