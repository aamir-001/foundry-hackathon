"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import type { TriageRow } from "@/lib/supabase/types";
import { FACILITY_NAME } from "@/lib/supabase/queries";

type Lane = "all" | "auto_accept" | "flag_for_review" | "reject";
type SortKey = "score" | "patient_id" | "facility_id";

const LANES: { key: Lane; label: string }[] = [
  { key: "flag_for_review", label: "Review" },
  { key: "auto_accept", label: "Act on" },
  { key: "reject", label: "Skip" },
  { key: "all", label: "All" },
];

export default function Worklist({ rows }: { rows: TriageRow[] }) {
  const [lane, setLane] = useState<Lane>("flag_for_review");
  const [sort, setSort] = useState<SortKey>("score");
  const [asc, setAsc] = useState(true);

  const filtered = useMemo(() => {
    const r = lane === "all" ? rows : rows.filter((x) => x.routing_decision === lane);
    const sorted = [...r].sort((a, b) => {
      let av: number | string = "";
      let bv: number | string = "";
      if (sort === "score") {
        av = a.score ?? -1;
        bv = b.score ?? -1;
      } else if (sort === "patient_id") {
        av = a.patient_id;
        bv = b.patient_id;
      } else {
        av = a.facility_id ?? 0;
        bv = b.facility_id ?? 0;
      }
      const cmp = av < bv ? -1 : av > bv ? 1 : 0;
      return asc ? cmp : -cmp;
    });
    return sorted;
  }, [rows, lane, sort, asc]);

  const toggleSort = (k: SortKey) => {
    if (k === sort) setAsc(!asc);
    else {
      setSort(k);
      setAsc(true);
    }
  };

  return (
    <div className="panel">
      <h2>Worklist ({filtered.length})</h2>
      <div className="controls">
        {LANES.map((l) => (
          <button key={l.key} className={lane === l.key ? "on" : ""} onClick={() => setLane(l.key)}>
            {l.label} ({l.key === "all" ? rows.length : rows.filter((x) => x.routing_decision === l.key).length})
          </button>
        ))}
      </div>
      <table>
        <thead>
          <tr>
            <th onClick={() => toggleSort("patient_id")}>Patient</th>
            <th onClick={() => toggleSort("facility_id")}>Facility</th>
            <th>Decision</th>
            <th onClick={() => toggleSort("score")}>Score</th>
            <th>Wound</th>
            <th>Reason</th>
          </tr>
        </thead>
        <tbody>
          {filtered.map((r) => (
            <tr key={r.patient_id}>
              <td>
                <Link href={`/patient/${r.patient_id}`}>{r.patient_id}</Link>
                <div className="muted" style={{ fontSize: "0.72rem" }}>
                  {[r.first_name, r.last_name].filter(Boolean).join(" ")}
                </div>
              </td>
              <td className="muted">{r.facility_id ? FACILITY_NAME[r.facility_id] : "—"}</td>
              <td>
                <span className={`badge ${r.routing_decision}`}>{r.routing_decision?.replace(/_/g, " ")}</span>
              </td>
              <td>{r.score ?? "—"}</td>
              <td className="muted">
                {r.wound_type ?? "—"}
                {r.is_multi_wound ? " ⊕" : ""}
              </td>
              <td className="reason-cell">{r.reason}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
