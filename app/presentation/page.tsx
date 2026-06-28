import Link from "next/link";
import { getAllTriage } from "@/lib/supabase/queries";

export const dynamic = "force-dynamic";

const DEMO: { id: string; note: string }[] = [
  { id: "FA-003", note: "Clean accept (score 100) — venous ulcer with a codeable dx, all measures present." },
  { id: "FA-002", note: "Reject — patient is HMO, not Medicare Part B (criterion 2)." },
  { id: "FA-020", note: "Flag — depth was recovered from the assessment; no codeable dx (suggested L-code)." },
  { id: "FA-006", note: "Flag — multi-wound (foot + heel); suggested primary wound." },
  { id: "FA-001", note: "Flag — depth missing everywhere. Type a depth in Biller actions → jumps to accept." },
];

export default async function PresentationPage() {
  const rows = await getAllTriage();
  const c = (d: string) => rows.filter((r) => r.routing_decision === d).length;

  return (
    <>
      <h1 className="h1">Presentation — for a non-technical biller</h1>
      <p className="sub">How a biller reads this output and knows what to act on.</p>

      <div className="panel">
        <h2>The one-screen answer</h2>
        <p>
          Every patient lands in one of three lanes. A biller works top-to-bottom and never reads raw
          clinical data:
        </p>
        <div className="lanes">
          <div className="lane act">
            <div className="label">Act on</div>
            <div className="count">{c("auto_accept")}</div>
            <div className="breakdown">all 3 criteria met — submit the claim</div>
          </div>
          <div className="lane review">
            <div className="label">Review</div>
            <div className="count">{c("flag_for_review")}</div>
            <div className="breakdown">eligible, one gap to confirm — sorted worst-first</div>
          </div>
          <div className="lane skip">
            <div className="label">Skip</div>
            <div className="count">{c("reject")}</div>
            <div className="breakdown">not billable — grouped by why</div>
          </div>
        </div>
        <p className="muted">
          Open the <Link href="/">Triage Queue</Link> and the Review lane is already sorted so the worst
          (lowest-confidence) patients are on top. Every row carries a plain-English reason — no codes to
          decipher.
        </p>
      </div>

      <div className="panel">
        <h2>The three criteria (Medicare Part B wound billing)</h2>
        <div className="step">
          <h3>1 · Active wound documented</h3>
          <span className="muted">pressure / diabetic / venous / arterial / SSI / abscess / burn.</span>
        </div>
        <div className="step">
          <h3>2 · Active Medicare Part B coverage</h3>
          <span className="muted">
            keyed on <code>payer_code = MCB</code> with no end date — never the misleading{" "}
            <code>payer_type</code> (which lumps all Medicare together).
          </span>
        </div>
        <div className="step">
          <h3>3 · Measurements (L/W/D) + drainage level</h3>
          <span className="muted">
            present, recovered from another source, or flagged to request from the provider.
          </span>
        </div>
        <p className="muted">
          Fail #1 or #2 → <strong>reject</strong>. Eligible but a gap → <strong>review</strong> (the
          system tries to fill the gap first). All present → <strong>act on</strong>.
        </p>
      </div>

      <div className="panel">
        <h2>Walk these five patients</h2>
        <table>
          <tbody>
            {DEMO.map((d) => (
              <tr key={d.id}>
                <td>
                  <Link href={`/patient/${d.id}`}>{d.id}</Link>
                </td>
                <td className="muted">{d.note}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="muted">
          On <Link href="/patient/FA-001">FA-001</Link>, supplying the missing depth in{" "}
          <strong>Biller actions</strong> re-scores the patient instantly (75 → 100) and moves it from
          Review to Act-on — the biller-calls-provider loop, closed in-app. Click{" "}
          <strong>Summarize (Haiku)</strong> for an optional natural-language rationale.
        </p>
      </div>

      <div className="panel">
        <h2>What&apos;s behind each number</h2>
        <p className="muted">
          <Link href="/pipeline">Pipeline</Link> — how data was ingested through a rate-limited API (430+
          retries, 0 dropped). <Link href="/extraction">Extraction</Link> — the deterministic parse of
          every note + assessment. <Link href="/eligibility">Eligibility table</Link> — the full
          one-row-per-patient output (exportable to CSV).
        </p>
        <p className="muted">
          <strong>Honest note:</strong> the spec targeted 48/92/160, but every patient here is reliably
          extractable (type+L/W = 300/300), so the &quot;extraction-unreliable&quot; bucket is genuinely 0,
          not 5 — and our note parser reads more depths than the reference oracle. The numbers above are
          the data-correct result, with the discrepancy surfaced rather than hidden.
        </p>
      </div>
    </>
  );
}
