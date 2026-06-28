import time
import requests

BASE_URL = "https://hackathon.prod.pulsefoundry.ai"


def get_with_retry(endpoint, params=None, max_retries=6):
    url = f"{BASE_URL}{endpoint}"

    for attempt in range(max_retries):
        try:
            response = requests.get(url, params=params, timeout=30)
        except requests.RequestException as e:
            if attempt == max_retries - 1:
                return {"status": "failed", "data": None, "error": str(e), "attempts": attempt + 1}
            time.sleep(2 * (attempt + 1))
            continue

        if response.status_code == 200:
            return {"status": "success", "data": response.json(), "error": None, "attempts": attempt + 1}

        if response.status_code == 429:
            retry_after = int(response.headers.get("Retry-After", 3))
            time.sleep(retry_after)
            continue

        return {
            "status": "failed",
            "data": None,
            "error": f"{response.status_code}: {response.text}",
            "attempts": attempt + 1,
        }

    return {"status": "failed_after_retry", "data": None, "error": "Exceeded max retries (429)", "attempts": max_retries}


def fetch_patients(facility_id):
    return get_with_retry("/pcc/patients", params={"facility_id": facility_id})


def fetch_diagnoses(patient_id):
    return get_with_retry("/pcc/diagnoses", params={"patient_id": patient_id})


def fetch_coverage(patient_id):
    return get_with_retry("/pcc/coverage", params={"patient_id": patient_id})


def fetch_notes(internal_id):
    return get_with_retry("/pcc/notes", params={"patient_id": internal_id})


def fetch_assessments(internal_id):
    return get_with_retry("/pcc/assessments", params={"patient_id": internal_id})
