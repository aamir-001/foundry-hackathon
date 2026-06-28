import json

p = json.load(open("/Users/adithyahnair/Downloads/abi-hackathon/patients.json"))
hdr = f"{'id':>3}  {'patient':<7} {'fac':>3}  {'name':<26} {'DOB':<10} {'sex':<6} {'payer':<5} {'new'}"
print(hdr)
print("-" * len(hdr))
for r in p:
    name = f"{r['first_name'] or ''} {r['last_name'] or ''}".strip()
    print(
        f"{r['id']:>3}  {r['patient_id']:<7} {r['facility_id']:>3}  {name:<26} "
        f"{r['birth_date'] or '':<10} {r['gender'] or '':<6} {r['primary_payer_code'] or '':<5} "
        f"{'Y' if r['is_new_admission'] else ''}"
    )
