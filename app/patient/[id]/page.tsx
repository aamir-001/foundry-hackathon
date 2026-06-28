import Link from "next/link";
import { getPatientDetail, FACILITY_NAME } from "@/lib/supabase/queries";
import { flattenAssessment, isNarrativeAssessment } from "@/lib/extract/structured";
import SummarizeButton from "@/components/SummarizeButton";
import FeedbackPanel from "@/components/FeedbackPanel";
import type { FieldStatusEntry } from "@/lib/supabase/types";

export const dynamic = "force-dynamic";

const FIELD_ORDER = [
  "wound_type",
  "location",
  "laterality",
  "stage",
  "length_cm",
  "width_cm",
  "depth_cm",
  "drainage_amount",
  "wound_dx_code",
  "suggested_primary",
];

const REJECT_CRITERION: Record<string, string> = {
  not_medicare_b: "Criterion 2 — no active Medicare Part B coverage.",
  no_active_wound: "Criterion 1 — no active wound documented.",
  extraction_unreliable: "Criterion 3 — wound type/measurements not determinable.",
};

export default async function PatientPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const detail = await getPatientDetail(id);
  const t = detail.triage;

  if (!t) {
    return (
      <main className="wrap">
        <p>
          <Link href="/">← worklist</Link>
        </p>
        <h1>{id}</h1>
        <p className="muted">No triage row found for this patient.</p>
      </main>
    );
  }

  const fieldStatus = (t.field_status ?? {}) as Record<string, FieldStatusEntry>;
  const a = detail.assessments[0];
  const aFields = a ? flattenAssessment(a.raw_json) : {};
  const narrative = a ? isNarrativeAssessment(aFields) : false;
  const soft = (t.flags ?? []).filter((f) =>
    ["size_outlier", "depth_outlier", "tissue_pct", "garbled_location_recovered", "drainage_type_conflict"].includes(f),
  );

  return (
    <main className="wrap">
      <p>
        <Link href="/">← worklist</Link>
      </p>
      <h1>
        {id} · {[t.first_name, t.last_name].filter(Boolean).join(" ")}{" "}
        <span className={`badge ${t.routing_decision}`}>{t.routing_decision?.replace(/_/g, " ")}</span>
      </h1>
      <p className="sub">
        {t.facility_id ? FACILITY_NAME[t.facility_id] : ""} · {t.wound_type ?? "—"}
        {t.is_multi_wound ? " (multi-wound)" : ""} · score {t.score ?? "—"}
      </p>

      {/* decision + reason */}
      <div className="panel">
        <h2>Decision</h2>
        <p>{t.reason}</p>
        {t.reject_reason && (
          <p className="conflict">Failed: {REJECT_CRITERION[t.reject_reason] ?? t.reject_reason}</p>
        )}
        <div style={{ display: "flex", gap: "1rem", marginTop: "0.5rem", flexWrap: "wrap" }} className="muted">
          <span>active wound: {yn(t.has_active_wound)}</span>
          <span>active MCB: {yn(t.has_active_mcb)}</span>
          <span>measures L/W: {yn(t.has_required_measures)}</span>
          <span>codeable dx: {yn(t.has_wound_dx_code)}</span>
        </div>
        {soft.length > 0 && (
          <div style={{ marginTop: "0.5rem" }}>
            {soft.map((s) => (
              <span key={s} className="badge soft" style={{ marginRight: "0.4rem" }}>
                {s.replace(/_/g, " ")} (advisory)
              </span>
            ))}
          </div>
        )}
        <div style={{ marginTop: "0.75rem" }}>
          <SummarizeButton patientId={id} initial={t.narrative} />
        </div>
      </div>

      {/* feedback loop (§12) */}
      <FeedbackPanel patientId={id} fieldStatus={fieldStatus} status={t.status ?? "pending"} />

      {/* extracted fields + recovery tiers */}
      <div className="panel">
        <h2>Extracted fields &amp; recovery</h2>
        <table>
          <thead>
            <tr>
              <th>Field</th>
              <th>Value</th>
              <th>Status</th>
              <th>Source</th>
            </tr>
          </thead>
          <tbody>
            {FIELD_ORDER.filter((f) => fieldStatus[f]).map((f) => {
              const fs = fieldStatus[f];
              return (
                <tr key={f}>
                  <td>{f.replace(/_/g, " ")}</td>
                  <td>{fs.value == null ? "—" : String(fs.value)}</td>
                  <td>
                    <span className={`tier ${fs.tier}`}>{fs.tier}</span>
                  </td>
                  <td className="muted">{fs.source}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* dual-source view */}
      <div className="panel">
        <h2>Sources (assessment vs notes)</h2>
        <div className="two-col">
          <div className="src">
            <h3>
              Assessment · {a?.assessment_type ?? "—"} ({narrative ? "narrative" : "structured"})
            </h3>
            {narrative ? (
              <div className="note-text">{aFields["Wound narrative"]}</div>
            ) : (
              <table>
                <tbody>
                  {Object.entries(aFields).map(([k, v]) => (
                    <tr key={k}>
                      <td className="muted">{k}</td>
                      <td>{v}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
          <div className="src">
            <h3>Progress notes ({detail.notes.length})</h3>
            {detail.notes.map((n, i) => (
              <div key={n.id} style={{ marginBottom: i < detail.notes.length - 1 ? "0.75rem" : 0 }}>
                <div className="muted" style={{ fontSize: "0.72rem" }}>
                  {n.note_type} · {n.effective_date?.slice(0, 10)} {i === 0 ? "(primary)" : "(sibling)"}
                </div>
                <div className="note-text">{n.note_text}</div>
              </div>
            ))}
          </div>
        </div>
        <div style={{ marginTop: "0.75rem" }} className="muted">
          <strong>Diagnoses:</strong>{" "}
          {detail.diagnoses.map((d) => `${d.icd10_code} (${d.clinical_status})`).join(" · ") || "—"}
          <br />
          <strong>Coverage:</strong>{" "}
          {detail.coverage
            .map((c) => `${c.payer_code}${c.effective_to ? ` (ended ${c.effective_to.slice(0, 10)})` : " active"}`)
            .join(" · ") || "—"}
        </div>
      </div>
    </main>
  );
}

function yn(v: boolean | null): string {
  return v == null ? "?" : v ? "✓" : "✗";
}
