import { getAllTriage, getQaStats } from "@/lib/supabase/queries";
import DataTable from "@/components/DataTable";

export const dynamic = "force-dynamic";

export default async function ExtractionPage() {
  const rows = await getAllTriage();
  const qa = await getQaStats(rows);
  const cov = {
    typeLW: rows.filter((r) => r.wound_type && r.length_cm != null && r.width_cm != null).length,
    drainage: rows.filter((r) => r.drainage_amount != null).length,
    depth: rows.filter((r) => r.depth_cm != null).length,
  };

  return (
    <>
      <h1 className="h1">Wound data extraction</h1>
      <p className="sub">
        Deterministic parse of every assessment + progress note → wound type · stage · location ·
        L/W/D (cm) · drainage (none/light/moderate/heavy). No LLM in the pipeline.
      </p>

      <div className="panel">
        <h2>Coverage</h2>
        <div className="qa-grid">
          <div className="qa-item">
            <div className="k">type + L + W</div>
            <div className="v">{cov.typeLW}/300</div>
          </div>
          <div className="qa-item">
            <div className="k">drainage amount</div>
            <div className="v">{cov.drainage}/300</div>
          </div>
          <div className="qa-item">
            <div className="k">depth</div>
            <div className="v">{cov.depth}/300</div>
          </div>
          <div className="qa-item">
            <div className="k">assessment format</div>
            <div className="v">
              {qa.structured} struct · {qa.narrative} narr
            </div>
          </div>
          <div className="qa-item">
            <div className="k">multi-wound</div>
            <div className="v">{qa.signals.multi_wound}</div>
          </div>
        </div>
        <p className="muted" style={{ marginTop: "0.75rem" }}>
          Two assessment sub-schemas (219 labeled-field / 81 free-text narrative) + three note formats
          (Envive, prose-measures, prose-Meas). Parser handles <code>cm</code> between dims
          (2.9&nbsp;cm&nbsp;x&nbsp;2.8), location from narrative (&quot;…to Right hip&quot;), strips
          <code> aprx</code>, dedupes <code>diabetic diabetic</code>. &quot;Depth source&quot; shows whether
          each value was <span className="tier present">present</span> in the primary note,{" "}
          <span className="tier recovered">recovered</span> from a sibling/assessment, or{" "}
          <span className="tier unavailable">unavailable</span>. Open a patient for the side-by-side
          source parse.
        </p>
      </div>

      <DataTable rows={rows} variant="extraction" filename="extraction.csv" filterable={false} />
    </>
  );
}
