from pipeline.database import init_db
from pipeline.ingest import ingest_all
from pipeline.extract import run_extraction
from pipeline.eligibility import run_eligibility


def run_pipeline():
    print("=" * 60)
    print("ABI FRAMEWORKS — WOUND CARE BILLING PIPELINE")
    print("=" * 60)

    print("\n--- STEP 1: Initialize Database ---")
    init_db()

    print("\n--- STEP 2: Ingest Data from PCC API ---")
    ingest_all()

    print("\n--- STEP 3: Extract Wound Data ---")
    run_extraction()

    print("\n--- STEP 4: Run Eligibility Decisions ---")
    run_eligibility()

    print("\n" + "=" * 60)
    print("PIPELINE COMPLETE")
    print("=" * 60)
    print("Run the dashboard:  streamlit run dashboard.py")


if __name__ == "__main__":
    run_pipeline()
