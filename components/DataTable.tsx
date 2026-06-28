"use client";

import Link from "next/link";
import { useMemo, useState, type ReactNode } from "react";
import type { TriageRow, FieldStatusEntry } from "@/lib/supabase/types";

const FACILITY: Record<number, string> = { 101: "Facility A", 102: "Facility B", 103: "Facility C" };
const DECISIONS = ["all", "auto_accept", "flag_for_review", "reject"];

interface Column {
  key: string;
  label: string;
  value: (r: TriageRow) => string | number;
  render?: (r: TriageRow) => ReactNode;
}

const num = (v: number | null) => (v == null ? "—" : String(v));
const dims = (r: TriageRow) =>
  [r.length_cm, r.width_cm, r.depth_cm].map((v) => (v == null ? "?" : v)).join("×");
const depthTier = (r: TriageRow): string =>
  (r.field_status as Record<string, FieldStatusEntry> | null)?.depth_cm?.tier ?? "—";
const patientCol: Column = {
  key: "patient_id",
  label: "Patient",
  value: (r) => r.patient_id,
  render: (r) => <Link href={`/patient/${r.patient_id}`}>{r.patient_id}</Link>,
};

// Column sets live in the client component so no functions cross the server→client boundary.
const VARIANTS: Record<string, Column[]> = {
  eligibility: [
    patientCol,
    { key: "name", label: "Name", value: (r) => [r.first_name, r.last_name].filter(Boolean).join(" ") },
    { key: "facility", label: "Facility", value: (r) => (r.facility_id ? FACILITY[r.facility_id] : "") },
    { key: "wound_type", label: "Wound type", value: (r) => r.wound_type ?? "" },
    { key: "stage", label: "Stage", value: (r) => r.stage ?? "" },
    { key: "location", label: "Location", value: (r) => r.location ?? "" },
    { key: "dims", label: "L×W×D (cm)", value: (r) => dims(r) },
    { key: "drainage", label: "Drainage", value: (r) => r.drainage_amount ?? "" },
    {
      key: "mcb",
      label: "Active MCB",
      value: (r) => (r.has_active_mcb ? "yes" : "no"),
      render: (r) => (r.has_active_mcb ? "✓" : "✗"),
    },
    {
      key: "decision",
      label: "Decision",
      value: (r) => r.routing_decision ?? "",
      render: (r) => <span className={`badge ${r.routing_decision}`}>{r.routing_decision?.replace(/_/g, " ")}</span>,
    },
    { key: "score", label: "Score", value: (r) => (r.score == null ? "" : r.score) },
    { key: "reason", label: "Reason", value: (r) => r.reason ?? "", render: (r) => <span className="reason-cell">{r.reason}</span> },
  ],
  extraction: [
    patientCol,
    { key: "wound_type", label: "Wound type", value: (r) => r.wound_type ?? "" },
    { key: "stage", label: "Stage", value: (r) => r.stage ?? "" },
    { key: "location", label: "Location", value: (r) => r.location ?? "" },
    { key: "laterality", label: "Laterality", value: (r) => r.laterality ?? "" },
    { key: "length_cm", label: "L (cm)", value: (r) => num(r.length_cm) },
    { key: "width_cm", label: "W (cm)", value: (r) => num(r.width_cm) },
    { key: "depth_cm", label: "D (cm)", value: (r) => num(r.depth_cm) },
    {
      key: "depth_src",
      label: "Depth source",
      value: (r) => depthTier(r),
      render: (r) => <span className={`tier ${depthTier(r)}`}>{depthTier(r)}</span>,
    },
    { key: "drainage_amount", label: "Drainage", value: (r) => r.drainage_amount ?? "" },
    { key: "multi", label: "Multi", value: (r) => (r.is_multi_wound ? "yes" : ""), render: (r) => (r.is_multi_wound ? "⊕" : "") },
  ],
};

function csv(v: string | number): string {
  const s = String(v ?? "");
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

export default function DataTable({
  rows,
  variant,
  filename,
  filterable = true,
}: {
  rows: TriageRow[];
  variant: keyof typeof VARIANTS;
  filename: string;
  filterable?: boolean;
}) {
  const columns = VARIANTS[variant];
  const [q, setQ] = useState("");
  const [dec, setDec] = useState("all");

  const filtered = useMemo(() => {
    const needle = q.toLowerCase();
    return rows.filter((r) => {
      if (dec !== "all" && r.routing_decision !== dec) return false;
      if (
        needle &&
        !`${r.patient_id} ${r.first_name ?? ""} ${r.last_name ?? ""} ${r.wound_type ?? ""}`
          .toLowerCase()
          .includes(needle)
      )
        return false;
      return true;
    });
  }, [rows, q, dec]);

  function exportCsv() {
    const header = columns.map((c) => c.label).join(",");
    const lines = filtered.map((r) => columns.map((c) => csv(c.value(r))).join(","));
    const blob = new Blob([header + "\n" + lines.join("\n")], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="card">
      <div className="controls">
        {filterable && (
          <>
            <input
              className="search-input"
              placeholder="filter patient / wound…"
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
            {DECISIONS.map((d) => (
              <button key={d} type="button" className={`tab${dec === d ? " on" : ""}`} onClick={() => setDec(d)}>
                {d.replace(/_/g, " ")}
              </button>
            ))}
          </>
        )}
        <button type="button" className="iconbtn prim" onClick={exportCsv} style={{ marginLeft: "auto" }}>
          Export CSV ({filtered.length})
        </button>
      </div>
      <div className="scroll-x">
        <table>
          <thead>
            <tr>
              {columns.map((c) => (
                <th key={c.key}>{c.label}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {filtered.map((r) => (
              <tr key={r.patient_id}>
                {columns.map((c) => (
                  <td key={c.key}>{c.render ? c.render(r) : c.value(r)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
