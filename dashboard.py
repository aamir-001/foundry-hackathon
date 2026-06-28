import streamlit as st
import sqlite3
import json
import pandas as pd

DB_PATH = "hackathon.db"

st.set_page_config(page_title="Wound Care Billing Dashboard", layout="wide")


@st.cache_data(ttl=30)
def load_decisions():
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("SELECT * FROM eligibility_decisions", conn)
    conn.close()
    return df


@st.cache_data(ttl=30)
def load_fetch_status():
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("SELECT * FROM api_fetch_status", conn)
    conn.close()
    return df


@st.cache_data(ttl=30)
def load_wound_extractions():
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("SELECT * FROM wound_extractions", conn)
    conn.close()
    return df


@st.cache_data(ttl=30)
def load_notes_for_patient(internal_id):
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query(
        "SELECT * FROM raw_notes WHERE patient_id = ?", conn, params=(internal_id,)
    )
    conn.close()
    return df


@st.cache_data(ttl=30)
def load_assessments_for_patient(internal_id):
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query(
        "SELECT * FROM raw_assessments WHERE patient_id = ?", conn, params=(internal_id,)
    )
    conn.close()
    return df


FACILITY_NAMES = {101: "Facility A", 102: "Facility B", 103: "Facility C"}
DECISION_COLORS = {
    "auto_accept": "#28a745",
    "flag_for_review": "#ffc107",
    "reject": "#dc3545",
}


def main():
    st.title("Wound Care Billing Dashboard")
    st.markdown("Medicare Part B eligibility triage for wound care patients")

    try:
        df = load_decisions()
    except Exception:
        st.error("No data found. Run the pipeline first: `python -m pipeline.main`")
        return

    if df.empty:
        st.warning("No eligibility decisions yet. Run the pipeline first.")
        return

    # --- Summary metrics ---
    st.markdown("---")
    col1, col2, col3, col4, col5 = st.columns(5)
    total = len(df)
    auto = len(df[df["decision"] == "auto_accept"])
    review = len(df[df["decision"] == "flag_for_review"])
    reject = len(df[df["decision"] == "reject"])
    flagged = int((df["flag_count"] > 0).sum()) if "flag_count" in df.columns else 0

    col1.metric("Total Patients", total)
    col2.metric("Ready for Billing", auto, delta=f"{auto/total*100:.0f}%")
    col3.metric("Needs Review", review, delta=f"{review/total*100:.0f}%", delta_color="off")
    col4.metric("Rejected", reject, delta=f"{reject/total*100:.0f}%", delta_color="inverse")
    col5.metric("Compliance Flags", flagged, delta="audit risk" if flagged else "clear", delta_color="inverse")

    # --- Filters ---
    st.markdown("---")
    filter_col1, filter_col2, filter_col3 = st.columns(3)

    with filter_col1:
        facility_options = ["All"] + sorted(df["facility_id"].unique().tolist())
        facility_filter = st.selectbox(
            "Facility",
            facility_options,
            format_func=lambda x: "All Facilities" if x == "All" else FACILITY_NAMES.get(x, f"Facility {x}")
        )

    with filter_col2:
        decision_options = ["All", "auto_accept", "flag_for_review", "reject"]
        decision_filter = st.selectbox("Routing Decision", decision_options)

    with filter_col3:
        wound_types = ["All"] + sorted([w for w in df["wound_type"].dropna().unique().tolist()])
        wound_filter = st.selectbox("Wound Type", wound_types)

    filtered = df.copy()
    if facility_filter != "All":
        filtered = filtered[filtered["facility_id"] == facility_filter]
    if decision_filter != "All":
        filtered = filtered[filtered["decision"] == decision_filter]
    if wound_filter != "All":
        filtered = filtered[filtered["wound_type"] == wound_filter]

    # --- Decision breakdown by facility ---
    st.markdown("---")
    st.subheader("Decision Breakdown by Facility")
    chart_col1, chart_col2 = st.columns(2)

    with chart_col1:
        pivot = df.groupby(["facility_id", "decision"]).size().unstack(fill_value=0)
        pivot.index = [FACILITY_NAMES.get(fid, f"Facility {fid}") for fid in pivot.index]
        st.bar_chart(pivot)

    with chart_col2:
        wound_counts = df["wound_type"].value_counts().head(10)
        if not wound_counts.empty:
            st.bar_chart(wound_counts)

    # --- Compliance / Audit-Risk Flags ---
    st.markdown("---")
    st.subheader("Compliance & Denial-Risk Flags")
    st.caption(
        "Audit-risk patterns layered on top of eligibility. These flags surface "
        "denial risk before a claim is submitted — and can downgrade an auto-accept to review."
    )

    if "compliance_flags" in df.columns:
        flagged_df = df[df["flag_count"] > 0].copy()
    else:
        flagged_df = df.iloc[0:0].copy()

    if flagged_df.empty:
        st.success("No compliance flags raised on the current dataset — no audit-risk patterns detected.")
    else:
        flag_rows = []
        for _, row in flagged_df.iterrows():
            try:
                flags = json.loads(row["compliance_flags"]) if row["compliance_flags"] else []
            except (json.JSONDecodeError, TypeError):
                flags = []
            for f in flags:
                flag_rows.append({
                    "Patient": row["patient_id"],
                    "Name": f"{row.get('first_name', '')} {row.get('last_name', '')}".strip(),
                    "Facility": FACILITY_NAMES.get(row["facility_id"], row["facility_id"]),
                    "Flag": f.get("code", ""),
                    "Decision": row["decision"],
                    "Wound": row.get("wound_type", ""),
                    "Stage": row.get("wound_stage", ""),
                    "Detail": f.get("message", ""),
                })

        flag_table = pd.DataFrame(flag_rows)

        fcol1, fcol2 = st.columns([1, 2])
        with fcol1:
            st.metric("Flagged Patients", len(flagged_df))
            st.metric("Total Flags", len(flag_table))
        with fcol2:
            flag_type_counts = flag_table["Flag"].value_counts()
            st.bar_chart(flag_type_counts)

        st.dataframe(flag_table, use_container_width=True, hide_index=True)

    # --- Patient table ---
    st.markdown("---")
    st.subheader(f"Patient List ({len(filtered)} patients)")

    display_cols = [
        "patient_id", "first_name", "last_name", "facility_id",
        "decision", "has_medicare_b", "wound_type", "wound_stage",
        "wound_location", "length_cm", "width_cm", "depth_cm",
        "drainage", "sync_complete", "reason"
    ]
    available_cols = [c for c in display_cols if c in filtered.columns]

    def color_decision(val):
        color = DECISION_COLORS.get(val, "#666")
        return f"background-color: {color}; color: white; font-weight: bold; border-radius: 4px"

    styled = filtered[available_cols].style.applymap(
        color_decision, subset=["decision"]
    )
    st.dataframe(styled, use_container_width=True, height=500)

    # --- Patient detail ---
    st.markdown("---")
    st.subheader("Patient Detail View")

    patient_ids = filtered["patient_id"].tolist()
    if patient_ids:
        selected_pid = st.selectbox("Select Patient", patient_ids)
        patient_row = df[df["patient_id"] == selected_pid].iloc[0]

        detail_col1, detail_col2 = st.columns(2)

        with detail_col1:
            st.markdown("**Patient Info**")
            st.write(f"**Name:** {patient_row.get('first_name', '')} {patient_row.get('last_name', '')}")
            st.write(f"**ID:** {patient_row['patient_id']}")
            st.write(f"**Facility:** {FACILITY_NAMES.get(patient_row['facility_id'], patient_row['facility_id'])}")
            st.write(f"**Medicare B:** {'Yes' if patient_row['has_medicare_b'] else 'No'}")

            decision = patient_row["decision"]
            color = DECISION_COLORS.get(decision, "#666")
            st.markdown(f"**Decision:** <span style='background-color:{color}; color:white; padding:4px 12px; border-radius:4px; font-weight:bold'>{decision}</span>", unsafe_allow_html=True)
            st.write(f"**Reason:** {patient_row['reason']}")

            if patient_row.get("flag_count", 0) and patient_row.get("compliance_flags"):
                try:
                    pf = json.loads(patient_row["compliance_flags"])
                except (json.JSONDecodeError, TypeError):
                    pf = []
                for f in pf:
                    st.error(f"**{f.get('code', 'FLAG')}** — {f.get('message', '')}")

        with detail_col2:
            st.markdown("**Wound Details**")
            st.write(f"**Type:** {patient_row.get('wound_type', 'N/A')}")
            st.write(f"**Stage:** {patient_row.get('wound_stage', 'N/A')}")
            st.write(f"**Location:** {patient_row.get('wound_location', 'N/A')}")
            l = patient_row.get('length_cm', 'N/A')
            w = patient_row.get('width_cm', 'N/A')
            d = patient_row.get('depth_cm', 'N/A')
            st.write(f"**Measurements:** {l} x {w} x {d} cm")
            st.write(f"**Drainage:** {patient_row.get('drainage', 'N/A')}")
            st.write(f"**Sync Complete:** {'Yes' if patient_row.get('sync_complete') else 'No'}")
            if patient_row.get("failed_endpoints"):
                st.warning(f"Failed endpoints: {patient_row['failed_endpoints']}")

        # Clinical notes
        internal_id = patient_row["internal_id"]
        notes_df = load_notes_for_patient(int(internal_id))
        if not notes_df.empty:
            st.markdown("**Clinical Notes**")
            for _, note in notes_df.iterrows():
                with st.expander(f"Note #{note['id']} — {note.get('note_type', 'Unknown')} ({note.get('effective_date', 'N/A')})"):
                    st.text(note.get("note_text", "No text available"))

        assessments_df = load_assessments_for_patient(int(internal_id))
        if not assessments_df.empty:
            st.markdown("**Wound Assessments**")
            for _, assess in assessments_df.iterrows():
                with st.expander(f"Assessment #{assess['id']} — {assess.get('assessment_type', 'Unknown')} ({assess.get('assessment_date', 'N/A')})"):
                    st.json(assess.get("raw_json", "{}"))

        # Extraction details
        extractions = load_wound_extractions()
        patient_extractions = extractions[extractions["patient_id"] == selected_pid]
        if not patient_extractions.empty:
            st.markdown("**Extraction Results**")
            st.dataframe(patient_extractions[["source_type", "source_id", "wound_type",
                "wound_stage", "location", "length_cm", "width_cm", "depth_cm",
                "drainage", "extraction_method", "confidence"]], use_container_width=True)

    # --- Sync health ---
    st.markdown("---")
    st.subheader("API Sync Health")
    try:
        fetch_df = load_fetch_status()
        if not fetch_df.empty:
            sync_summary = fetch_df.groupby("status").size()
            st.bar_chart(sync_summary)

            failed = fetch_df[fetch_df["status"] != "success"]
            if not failed.empty:
                st.warning(f"{len(failed)} endpoint fetches failed")
                st.dataframe(failed, use_container_width=True)
            else:
                st.success("All API fetches completed successfully!")
    except Exception:
        st.info("No sync data available yet.")


if __name__ == "__main__":
    main()
