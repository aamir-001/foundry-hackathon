"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import type { FieldStatusEntry } from "@/lib/supabase/types";

const NUMERIC = new Set(["depth_cm", "length_cm", "width_cm"]);

export default function FeedbackPanel({
  patientId,
  fieldStatus,
  status,
}: {
  patientId: string;
  fieldStatus: Record<string, FieldStatusEntry>;
  status: string;
}) {
  const router = useRouter();
  const [busy, setBusy] = useState<string | null>(null);
  const [vals, setVals] = useState<Record<string, string>>({});
  const [msg, setMsg] = useState<string | null>(null);

  const gaps = Object.entries(fieldStatus).filter(
    ([, fs]) => fs.tier === "unavailable" || fs.tier === "suggested",
  );

  async function submitField(field: string) {
    const value = vals[field];
    if (value == null || value === "") return;
    setBusy(field);
    setMsg(null);
    try {
      const res = await fetch("/api/feedback", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ patient_id: patientId, field, value }),
      });
      const j = await res.json();
      if (!res.ok) throw new Error(j.error ?? "failed");
      setMsg(`${field.replace(/_/g, " ")} supplied → ${j.routing_decision?.replace(/_/g, " ")} (score ${j.score})`);
      router.refresh();
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "failed");
    } finally {
      setBusy(null);
    }
  }

  async function setStatus(s: string) {
    setBusy(s);
    setMsg(null);
    try {
      const res = await fetch("/api/feedback", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ patient_id: patientId, status: s }),
      });
      if (!res.ok) throw new Error((await res.json()).error ?? "failed");
      router.refresh();
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "failed");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="card">
      <h2>Biller actions</h2>
      <p className="muted" style={{ marginTop: 0 }}>
        Status: <strong>{status}</strong>
      </p>

      {gaps.length > 0 ? (
        <table>
          <thead>
            <tr>
              <th>Missing / suggested field</th>
              <th>Supply value</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {gaps.map(([field, fs]) => (
              <tr key={field}>
                <td>
                  {field.replace(/_/g, " ")} <span className={`tier ${fs.tier}`}>({fs.tier})</span>
                </td>
                <td>
                  <input
                    type={NUMERIC.has(field) ? "number" : "text"}
                    step="0.1"
                    value={vals[field] ?? ""}
                    placeholder={fs.tier === "suggested" ? String(fs.value ?? "") : ""}
                    onChange={(e) => setVals((v) => ({ ...v, [field]: e.target.value }))}
                    className="search-input"
                    style={{ width: 160 }}
                  />
                </td>
                <td>
                  <button className="btn" disabled={busy === field} onClick={() => submitField(field)}>
                    {busy === field ? "…" : "Submit"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="muted">No missing or suggested fields — nothing to supply.</p>
      )}

      <div className="controls" style={{ marginTop: "0.75rem" }}>
        <button onClick={() => setStatus("reviewed")} disabled={busy != null}>
          Mark reviewed
        </button>
        <button onClick={() => setStatus("submitted")} disabled={busy != null}>
          Submit claim
        </button>
        <button onClick={() => setStatus("dismissed")} disabled={busy != null}>
          Dismiss
        </button>
      </div>
      {msg && <p style={{ marginTop: "0.5rem" }}>{msg}</p>}
    </div>
  );
}
