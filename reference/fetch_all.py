#!/usr/bin/env python3
"""Fetch EVERY endpoint for ALL 300 patients and write one delineated text file.

Endpoints per patient:
  /pcc/diagnoses    (string patient_id, e.g. FA-001)
  /pcc/coverage     (string patient_id)
  /pcc/notes        (integer id)
  /pcc/assessments  (integer id)

Plus /pcc/patients (3 facilities) for the master list.

Handles the 30%-chance HTTP 429 by honoring Retry-After with backoff fallback.
Uses a thread pool so the ~1200 calls finish in minutes, not half an hour.
"""
import json
import time
import threading
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor

BASE_URL = "https://hackathon.prod.pulsefoundry.ai"
FACILITIES = [101, 102, 103]
MAX_RETRIES = 15
WORKERS = 10

_print_lock = threading.Lock()
_progress = {"done": 0, "total": 0, "retries": 0}


def log(msg):
    with _print_lock:
        print(msg, flush=True)


def get(path, params=None, max_retries=MAX_RETRIES):
    """GET a JSON endpoint, retrying on 429 / transient 5xx / network errors."""
    url = f"{BASE_URL}{path}"
    if params:
        query = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"{url}?{query}"

    attempt = 0
    while True:
        attempt += 1
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt <= max_retries:
                ra = e.headers.get("Retry-After")
                wait = int(ra) if ra and ra.isdigit() else min(2 ** attempt, 8)
                with _print_lock:
                    _progress["retries"] += 1
                time.sleep(wait)
                continue
            if e.code >= 500 and attempt <= max_retries:
                time.sleep(min(2 ** attempt, 8))
                continue
            raise
        except urllib.error.URLError:
            if attempt <= max_retries:
                time.sleep(min(2 ** attempt, 8))
                continue
            raise


def fetch_patient_record(p):
    """Fetch all four sub-resources for one patient."""
    sid = p["patient_id"]      # string id  -> diagnoses, coverage
    iid = p["id"]              # integer id -> notes, assessments
    rec = {"patient": p}
    rec["diagnoses"] = get("/pcc/diagnoses", {"patient_id": sid})
    rec["coverage"] = get("/pcc/coverage", {"patient_id": sid})
    rec["notes"] = get("/pcc/notes", {"patient_id": iid})
    rec["assessments"] = get("/pcc/assessments", {"patient_id": iid})

    with _print_lock:
        _progress["done"] += 1
        d = _progress["done"]
        t = _progress["total"]
    if d % 20 == 0 or d == t:
        log(f"  progress: {d}/{t} patients  (retries so far: {_progress['retries']})")
    return rec


def main():
    t0 = time.time()

    # Step 1: master patient list across all facilities
    log("Fetching master patient list (3 facilities)...")
    patients = []
    for fid in FACILITIES:
        rows = get("/pcc/patients", {"facility_id": fid})
        log(f"  facility {fid}: {len(rows)} patients")
        patients.extend(rows)
    patients.sort(key=lambda p: p["id"])
    _progress["total"] = len(patients)
    log(f"Total: {len(patients)} patients. Now fetching all sub-resources...\n")

    # Step 2: fetch all four endpoints per patient, concurrently
    records = {}
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futures = {ex.submit(fetch_patient_record, p): p["id"] for p in patients}
        for fut in futures:
            pass  # submission only; collect below
        for fut, pid in [(f, futures[f]) for f in futures]:
            records[pid] = fut.result()

    ordered = [records[p["id"]] for p in patients]

    # Step 3: save raw combined JSON (full fidelity)
    json_path = "/Users/adithyahnair/Downloads/abi-hackathon/all_patient_data.json"
    with open(json_path, "w") as f:
        json.dump(ordered, f, indent=2)

    # Step 4: write the delineated human-readable text file
    txt_path = "/Users/adithyahnair/Downloads/abi-hackathon/all_patient_data.txt"
    write_text_file(txt_path, ordered, t0)

    elapsed = time.time() - t0
    log(f"\nDONE. {len(ordered)} patients in {elapsed:.0f}s, {_progress['retries']} 429-retries.")
    log(f"  Text : {txt_path}")
    log(f"  JSON : {json_path}")


def pj(obj):
    """Pretty JSON, or a clear marker if empty/none."""
    if obj is None or obj == [] or obj == {}:
        return "  (none)"
    return "\n".join("  " + line for line in json.dumps(obj, indent=2).splitlines())


def write_text_file(path, records, t0):
    sep_major = "#" * 80
    sep_minor = "-" * 80
    lines = []
    lines.append("=" * 80)
    lines.append("ABI HACKATHON — COMPLETE PATIENT DATA EXPORT (ALL ENDPOINTS)")
    lines.append(f"Generated      : {time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"Base URL       : {BASE_URL}")
    lines.append(f"Total patients : {len(records)}")
    lines.append("Endpoints per patient: /pcc/patients, /pcc/diagnoses,")
    lines.append("                       /pcc/coverage, /pcc/notes, /pcc/assessments")
    lines.append("=" * 80)
    lines.append("")

    for rec in records:
        p = rec["patient"]
        name = f"{p.get('first_name') or ''} {p.get('last_name') or ''}".strip()
        lines.append(sep_major)
        lines.append(
            f"# PATIENT id={p['id']}  |  patient_id={p['patient_id']}  |  "
            f"{name}  |  Facility {p['facility_id']}"
        )
        lines.append(sep_major)
        lines.append("")

        lines.append(f"--- DEMOGRAPHICS  (GET /pcc/patients?facility_id={p['facility_id']}) ---")
        lines.append(pj(p))
        lines.append("")

        lines.append(f"--- DIAGNOSES  (GET /pcc/diagnoses?patient_id={p['patient_id']}) ---")
        lines.append(pj(rec["diagnoses"]))
        lines.append("")

        lines.append(f"--- COVERAGE  (GET /pcc/coverage?patient_id={p['patient_id']}) ---")
        lines.append(pj(rec["coverage"]))
        lines.append("")

        lines.append(f"--- PROGRESS NOTES  (GET /pcc/notes?patient_id={p['id']}) ---")
        lines.append(pj(rec["notes"]))
        lines.append("")

        lines.append(f"--- ASSESSMENTS  (GET /pcc/assessments?patient_id={p['id']}) ---")
        lines.append(pj(rec["assessments"]))
        lines.append("")
        lines.append(sep_minor)
        lines.append("")

    with open(path, "w") as f:
        f.write("\n".join(lines))


if __name__ == "__main__":
    main()
