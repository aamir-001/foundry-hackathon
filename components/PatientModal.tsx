"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import type { TriageRow } from "@/lib/supabase/types";
import { FACILITY_NAME } from "@/lib/supabase/queries";
import {
  buildRules,
  confidencePct,
  facilityLetter,
  patientName,
  sizeStr,
  toUiDecision,
  woundSubtitle,
} from "@/lib/ui/triage-display";

const GLYPH = { accept: "✓", flag: "▲", reject: "✕" } as const;
const LABEL = { accept: "AUTO-ACCEPT", flag: "REVIEW", reject: "REJECT" } as const;

interface NotePayload {
  note_text: string | null;
  note_type: string | null;
  effective_date: string | null;
}

export default function PatientModal({
  row,
  onClose,
  onStatus,
}: {
  row: TriageRow;
  onClose: () => void;
  onStatus: (patientId: string, status: string) => Promise<void>;
}) {
  const [note, setNote] = useState<NotePayload | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch(`/api/patient/${encodeURIComponent(row.patient_id)}`)
      .then((r) => r.json())
      .then((j) => {
        if (!cancelled && j.notes?.[0]) setNote(j.notes[0]);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [row.patient_id]);

  const dc = toUiDecision(row.routing_decision);
  const rules = buildRules(row);
  const conf = confidencePct(row);

  async function act(status: string) {
    setBusy(status);
    try {
      await onStatus(row.patient_id, status);
      onClose();
    } finally {
      setBusy(null);
    }
  }

  function exportRow() {
    const cols = [
      "patient_id",
      "name",
      "facility",
      "decision",
      "wound_type",
      "stage",
      "location",
      "size",
      "drainage",
      "score",
      "reason",
    ];
    const vals = [
      row.patient_id,
      patientName(row),
      row.facility_id ? FACILITY_NAME[row.facility_id] : "",
      row.routing_decision ?? "",
      row.wound_type ?? "",
      row.stage ?? "",
      row.location ?? "",
      sizeStr(row),
      row.drainage_amount ?? "",
      row.score ?? "",
      row.reason ?? "",
    ];
    const esc = (v: string | number) => `"${String(v).replace(/"/g, '""')}"`;
    const csv = [cols.join(","), vals.map(esc).join(",")].join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `patient_${row.patient_id}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="scrim" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="mhd">
          <div className="mtitle">
            <div className="fx ac gap10" style={{ flexWrap: "wrap" }}>
              <span className={`badge ${dc}`}>
                <span className="bglyph">{GLYPH[dc]}</span>
                {LABEL[dc]}
              </span>
              <span className="mname">{patientName(row)}</span>
            </div>
            <div className="patmeta mono mtmeta">
              {row.patient_id} · Facility {facilityLetter(row.facility_id)}
              {row.facility_id ? ` (${row.facility_id})` : ""} · status {row.status}
            </div>
          </div>
          <button type="button" className="closeb" onClick={onClose}>
            ✕
          </button>
        </div>
        <div className="mbody">
          <div className={`banner ${dc}`}>
            <span className="bgly">{GLYPH[dc]}</span>
            <span>{row.reason}</span>
          </div>
          <div>
            <div className="mseclbl">Extracted wound data</div>
            <div className="kv">
              {[
                { k: "Type", v: row.wound_type ?? "—" },
                { k: "Stage", v: row.stage ? `Stage ${row.stage}` : "n/a" },
                { k: "Location", v: row.location ?? "—" },
                { k: "Size (L×W×D)", v: sizeStr(row) },
                { k: "Drainage", v: row.drainage_amount ?? "—" },
                { k: "Wound summary", v: woundSubtitle(row) },
              ].map((e) => (
                <div key={e.k} className="kvi">
                  <div className="kvk">{e.k}</div>
                  <div className="kvv">{e.v}</div>
                </div>
              ))}
            </div>
          </div>
          <div>
            <div className="mseclbl">Why the system decided this</div>
            <div className="rules">
              {rules.map((r) => (
                <div key={r.k} className={`rule ${r.s}`}>
                  <div className="rico">{r.s === "pass" ? "✓" : r.s === "warn" ? "!" : "✕"}</div>
                  <div>
                    <div className="rk">{r.k}</div>
                    <div className="rn">{r.n}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>
          <div>
            <div className="mseclbl">Coverage &amp; eligibility</div>
            <div className="kv">
              {[
                { k: "Active MCB", v: row.has_active_mcb ? "yes" : "no" },
                { k: "Active wound", v: row.has_active_wound ? "yes" : "no" },
                { k: "Codeable dx", v: row.has_wound_dx_code ? "yes" : "no" },
                { k: "Score", v: row.score != null ? String(row.score) : "—" },
                { k: "Confidence", v: `${conf}%` },
                { k: "Multi-wound", v: row.is_multi_wound ? "yes" : "no" },
              ].map((m) => (
                <div key={m.k} className="kvi">
                  <div className="kvk">{m.k}</div>
                  <div className="kvv">{m.v}</div>
                </div>
              ))}
            </div>
          </div>
          <div>
            <div className="mseclbl">
              Source note{note?.note_type ? ` · ${note.note_type}` : ""} · {conf}% confidence
            </div>
            <div className="note">
              {note?.note_text ?? "Loading primary note…"}
            </div>
          </div>
        </div>
        <div className="mfoot">
          <button type="button" className="btn acc" disabled={!!busy} onClick={() => act("submitted")}>
            ✓ Accept &amp; bill
          </button>
          <button type="button" className="btn flag" disabled={!!busy} onClick={() => act("reviewed")}>
            ▲ Mark reviewed
          </button>
          <button type="button" className="btn rej" disabled={!!busy} onClick={() => act("dismissed")}>
            ✕ Dismiss
          </button>
          <div className="spacer" />
          <Link href={`/patient/${row.patient_id}`} className="btn">
            Full detail
          </Link>
          <button type="button" className="btn" onClick={exportRow}>
            Export row
          </button>
        </div>
      </div>
    </div>
  );
}
