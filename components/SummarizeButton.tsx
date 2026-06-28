"use client";

import { useState } from "react";

export default function SummarizeButton({
  patientId,
  initial,
}: {
  patientId: string;
  initial: string | null;
}) {
  const [text, setText] = useState<string | null>(initial);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function run() {
    setLoading(true);
    setErr(null);
    try {
      const res = await fetch(`/api/summarize${text ? "?refresh=1" : ""}`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ patient_id: patientId }),
      });
      const j = await res.json();
      if (!res.ok) throw new Error(j.error ?? "failed");
      setText(j.narrative);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div>
      <button className="btn" onClick={run} disabled={loading}>
        {loading ? "Summarizing…" : text ? "Re-summarize (Haiku)" : "Summarize (Haiku)"}
      </button>
      {err && <p style={{ color: "#f28b82", marginTop: "0.5rem" }}>{err}</p>}
      {text && <p style={{ marginTop: "0.5rem", fontStyle: "italic" }}>“{text}”</p>}
    </div>
  );
}
