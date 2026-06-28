#!/usr/bin/env python3
"""Fetch all 300 synthetic patients from the ABI hackathon mock PCC API.

Handles the API's 30%-chance 429 rate limiting by respecting the Retry-After
header with exponential-backoff fallback.
"""
import json
import time
import urllib.request
import urllib.error

BASE_URL = "https://hackathon.prod.pulsefoundry.ai"
FACILITIES = [101, 102, 103]
MAX_RETRIES = 12


def get(path, params=None, max_retries=MAX_RETRIES):
    """GET a JSON endpoint, retrying on 429 (and transient 5xx)."""
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
                retry_after = e.headers.get("Retry-After")
                wait = int(retry_after) if retry_after and retry_after.isdigit() else min(2 ** attempt, 8)
                print(f"  429 on {path} {params or ''} -> retry in {wait}s (attempt {attempt})")
                time.sleep(wait)
                continue
            if e.code >= 500 and attempt <= max_retries:
                wait = min(2 ** attempt, 8)
                print(f"  {e.code} on {path} {params or ''} -> retry in {wait}s (attempt {attempt})")
                time.sleep(wait)
                continue
            raise
        except urllib.error.URLError:
            if attempt <= max_retries:
                wait = min(2 ** attempt, 8)
                print(f"  network error on {path} -> retry in {wait}s (attempt {attempt})")
                time.sleep(wait)
                continue
            raise


def main():
    all_patients = []
    for fid in FACILITIES:
        print(f"Fetching patients for facility_id={fid} ...")
        patients = get("/pcc/patients", {"facility_id": fid})
        print(f"  -> {len(patients)} patients")
        all_patients.extend(patients)

    all_patients.sort(key=lambda p: p["id"])

    out_path = "/Users/adithyahnair/Downloads/abi-hackathon/patients.json"
    with open(out_path, "w") as f:
        json.dump(all_patients, f, indent=2)

    print(f"\nTotal patients fetched: {len(all_patients)}")
    print(f"Saved to: {out_path}")

    # Payer mix summary
    mix = {}
    for p in all_patients:
        code = p.get("primary_payer_code") or "UNKNOWN"
        mix[code] = mix.get(code, 0) + 1
    print("\nPayer mix:")
    for code, n in sorted(mix.items(), key=lambda x: -x[1]):
        print(f"  {code}: {n} ({n/len(all_patients)*100:.0f}%)")


if __name__ == "__main__":
    main()
