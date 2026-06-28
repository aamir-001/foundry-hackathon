import time
import random
import requests
import logging
from typing import Optional

log = logging.getLogger(__name__)
BASE_URL = "https://hackathon.prod.pulsefoundry.ai"
MAX_RETRIES = 8
_consecutive_429s = 0

def _get(endpoint, params):
    global _consecutive_429s
    url = f"{BASE_URL}{endpoint}"
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get(url, params=params, timeout=15)
            if resp.status_code == 200:
                _consecutive_429s = 0
                return resp.json(), 'ok'
            if resp.status_code == 429:
                _consecutive_429s += 1
                base_wait = int(resp.headers.get("Retry-After", 2))
                congestion_factor = 1 + (0.5 * _consecutive_429s)
                jitter = random.uniform(0, 1.0)
                wait = (base_wait * congestion_factor) + jitter
                log.warning(f"429 attempt {attempt+1} congestion={_consecutive_429s} wait={wait:.1f}s")
                time.sleep(wait)
                continue
            if resp.status_code == 422:
                return [], 'failed'
            time.sleep((2 ** attempt) + random.uniform(0, 1))
        except requests.RequestException as exc:
            log.error(f"Request error: {exc}")
            time.sleep((2 ** attempt) + random.uniform(0, 1))
    return [], 'failed'

def get_patients(facility_id, since=None):
    params = {"facility_id": facility_id}
    if since:
        params["since"] = since
    return _get("/pcc/patients", params)

def get_diagnoses(patient_id):
    return _get("/pcc/diagnoses", {"patient_id": patient_id})

def get_coverage(patient_id):
    return _get("/pcc/coverage", {"patient_id": patient_id})

def get_notes(internal_id, since=None):
    params = {"patient_id": internal_id}
    if since:
        params["since"] = since
    return _get("/pcc/notes", params)

def get_assessments(internal_id, since=None):
    params = {"patient_id": internal_id}
    if since:
        params["since"] = since
    return _get("/pcc/assessments", params)
