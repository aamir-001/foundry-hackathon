"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import type { TriageRow } from "@/lib/supabase/types";
import { FACILITY_NAME } from "@/lib/supabase/queries";
import SyncButton from "@/components/SyncButton";
import PatientModal from "@/components/PatientModal";
import { useTheme } from "@/components/AppShell";
import {
  confidencePct,
  facilityLetter,
  flagCategory,
  matchesConfFilter,
  matchesFacilityFilter,
  matchesSearch,
  matchesWoundFilter,
  patientName,
  severityScore,
  sparkPoints,
  toUiDecision,
  woundSubtitle,
  woundTitle,
  WOUND_TYPES,
} from "@/lib/ui/triage-display";

type Tab = "all" | "accept" | "flag" | "reject";
type SortKey = "name" | "sev" | "decision" | "conf";

const GLYPH = { accept: "✓", flag: "▲", reject: "✕" } as const;
const LABEL = { accept: "AUTO-ACCEPT", flag: "REVIEW", reject: "REJECT" } as const;
const TIP = {
  accept: "All Part B criteria met — safe to bill.",
  flag: "Needs a human before billing.",
  reject: "Fails a hard Medicare Part B eligibility gate.",
} as const;

function tabToDecision(tab: Tab): string | null {
  if (tab === "accept") return "auto_accept";
  if (tab === "flag") return "flag_for_review";
  if (tab === "reject") return "reject";
  return null;
}

export default function TriageDashboard({
  rows,
  mcbCount,
}: {
  rows: TriageRow[];
  mcbCount: number;
}) {
  const router = useRouter();
  const { dark, cb, toggleDark, toggleCb } = useTheme();
  const [tab, setTab] = useState<Tab>("flag");
  const [query, setQuery] = useState("");
  const [fWound, setFWound] = useState("all");
  const [fFac, setFFac] = useState("all");
  const [fConf, setFConf] = useState("all");
  const [sortKey, setSortKey] = useState<SortKey>("decision");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");
  const [sel, setSel] = useState<string[]>([]);
  const [modalId, setModalId] = useState<string | null>(null);
  const [insights, setInsights] = useState(true);

  const counts = useMemo(() => {
    const c = (d: string) => rows.filter((r) => r.routing_decision === d).length;
    return {
      accept: c("auto_accept"),
      flag: c("flag_for_review"),
      reject: c("reject"),
      total: rows.length,
    };
  }, [rows]);

  const nonMcb = rows.filter((r) => r.routing_decision === "reject" && !r.has_active_mcb).length;
  const nonMcbPct = counts.reject ? Math.round((nonMcb / counts.reject) * 100) : 0;

  const baseFiltered = useMemo(() => {
    return rows.filter(
      (r) =>
        matchesSearch(r, query) &&
        matchesWoundFilter(r, fWound) &&
        matchesFacilityFilter(r, fFac) &&
        matchesConfFilter(r, fConf),
    );
  }, [rows, query, fWound, fFac, fConf]);

  const tabCounts = useMemo(
    () => ({
      all: baseFiltered.length,
      flag: baseFiltered.filter((r) => r.routing_decision === "flag_for_review").length,
      accept: baseFiltered.filter((r) => r.routing_decision === "auto_accept").length,
      reject: baseFiltered.filter((r) => r.routing_decision === "reject").length,
    }),
    [baseFiltered],
  );

  const filtered = useMemo(() => {
    const dec = tabToDecision(tab);
    let list = dec ? baseFiltered.filter((r) => r.routing_decision === dec) : baseFiltered;
    const dord = { reject: 0, flag: 1, accept: 2 };
    const dir = sortDir === "asc" ? 1 : -1;
    list = [...list].sort((a, b) => {
      let av: number | string = 0;
      let bv: number | string = 0;
      if (sortKey === "name") {
        av = patientName(a);
        bv = patientName(b);
        return String(av).localeCompare(String(bv)) * dir;
      }
      if (sortKey === "sev") {
        av = severityScore(a);
        bv = severityScore(b);
      } else if (sortKey === "conf") {
        av = confidencePct(a);
        bv = confidencePct(b);
      } else {
        av = dord[toUiDecision(a.routing_decision)];
        bv = dord[toUiDecision(b.routing_decision)];
      }
      if (av === bv) return patientName(a).localeCompare(patientName(b));
      return ((av as number) - (bv as number)) * dir;
    });
    return list;
  }, [baseFiltered, tab, sortKey, sortDir]);

  const flagReasons = useMemo(() => {
    const tally: Record<string, number> = {};
    rows
      .filter((r) => r.routing_decision === "flag_for_review")
      .forEach((r) => {
        const c = flagCategory(r.reason ?? "");
        tally[c] = (tally[c] ?? 0) + 1;
      });
    const max = Math.max(1, ...Object.values(tally));
    return Object.entries(tally)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 6)
      .map(([label, count]) => ({ label, count, width: Math.round((count / max) * 100) }));
  }, [rows]);

  const facs = useMemo(() => {
    return [101, 102, 103].map((fid) => {
      const fp = rows.filter((r) => r.facility_id === fid);
      const t = fp.length || 1;
      const a = fp.filter((r) => r.routing_decision === "auto_accept").length;
      const fl = fp.filter((r) => r.routing_decision === "flag_for_review").length;
      const rj = fp.filter((r) => r.routing_decision === "reject").length;
      return {
        name: FACILITY_NAME[fid],
        total: fp.length,
        accW: Math.round((a / t) * 100),
        flagW: Math.round((fl / t) * 100),
        rejW: Math.round((rj / t) * 100),
      };
    });
  }, [rows]);

  const modalRow = modalId ? rows.find((r) => r.patient_id === modalId) : null;
  const visIds = filtered.map((r) => r.patient_id);
  const allSel = visIds.length > 0 && visIds.every((id) => sel.includes(id));

  function sort(k: SortKey) {
    if (k === sortKey) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else {
      setSortKey(k);
      setSortDir(k === "conf" || k === "sev" ? "desc" : "asc");
    }
  }

  function sortArrow(k: SortKey) {
    return sortKey === k ? (sortDir === "asc" ? "↑" : "↓") : "";
  }

  async function setStatus(patientId: string, status: string) {
    await fetch("/api/feedback", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ patient_id: patientId, status }),
    });
    router.refresh();
  }

  async function bulkStatus(status: string) {
    await Promise.all(sel.map((id) => setStatus(id, status)));
    setSel([]);
  }

  function exportCsv() {
    const cols = [
      "patient_id",
      "name",
      "facility_id",
      "decision",
      "wound_type",
      "stage",
      "location",
      "length_cm",
      "width_cm",
      "depth_cm",
      "drainage",
      "score",
      "confidence",
      "reason",
      "status",
    ];
    const esc = (v: unknown) => `"${String(v ?? "").replace(/"/g, '""')}"`;
    const lines = [
      cols.join(","),
      ...filtered.map((r) =>
        [
          r.patient_id,
          patientName(r),
          r.facility_id,
          r.routing_decision,
          r.wound_type,
          r.stage,
          r.location,
          r.length_cm,
          r.width_cm,
          r.depth_cm,
          r.drainage_amount,
          r.score,
          r.confidence,
          r.reason,
          r.status,
        ]
          .map(esc)
          .join(","),
      ),
    ];
    const blob = new Blob([lines.join("\n")], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "ouchless_triage.csv";
    a.click();
    URL.revokeObjectURL(url);
  }

  const seg = (n: number) => (counts.total ? Math.round((n / counts.total) * 100) : 0);
  const mcbPct = counts.total ? Math.round((mcbCount / counts.total) * 100) : 0;

  return (
    <>
      <div className="topbar">
        <div>
          <h1 className="h1">Triage Queue</h1>
          <div className="sub">
            {counts.total} patients in queue · {counts.total} ingested across 3 facilities · {mcbCount}{" "}
            Medicare Part B
          </div>
        </div>
        <div className="controls">
          <div className="search">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="11" cy="11" r="7" />
              <path d="m21 21-4.3-4.3" />
            </svg>
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search name, wound, reason…"
            />
          </div>
          <button
            type="button"
            className={`iconbtn${cb ? " on" : ""}`}
            onClick={toggleCb}
            title="Colorblind-safe palette"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="12" cy="12" r="9" />
              <path d="M12 3a9 9 0 0 0 0 18z" fill="currentColor" />
            </svg>
          </button>
          <button
            type="button"
            className={`iconbtn${dark ? " on" : ""}`}
            onClick={toggleDark}
            title="Toggle dark mode"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M21 12.8A9 9 0 1 1 11.2 3 7 7 0 0 0 21 12.8z" />
            </svg>
          </button>
          <SyncButton />
          <button type="button" className="iconbtn prim" onClick={exportCsv}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M12 3v12m0 0 4-4m-4 4-4-4M4 21h16" />
            </svg>
            Export CSV
          </button>
        </div>
      </div>

      <div className="kpis">
        <div className="kpi">
          <div className="cap">
            <span className="dot tl" />
            In queue
          </div>
          <div className="big">{counts.total}</div>
          <div className="ksub">Medicare Part B candidates</div>
        </div>
        <div className="kpi">
          <div className="cap">
            <span className="dot acc" />
            Auto-accept
          </div>
          <div className="big">{counts.accept}</div>
          <div className="ksub">Ready to bill</div>
        </div>
        <div className="kpi">
          <div className="cap">
            <span className="dot flag" />
            Flag for review
          </div>
          <div className="big">{counts.flag}</div>
          <div className="ksub">Needs a human check</div>
        </div>
        <div className="kpi">
          <div className="cap">
            <span className="dot rej" />
            Reject
          </div>
          <div className="big">{counts.reject}</div>
          <div className="ksub">{nonMcbPct}% non-Medicare</div>
        </div>
      </div>

      {insights && (
        <div className="insights">
          <div className="card">
            <div className="cardhd">
              <div className="cardttl">Triage funnel</div>
              <button type="button" className="linkb" onClick={() => setInsights(false)}>
                Hide
              </button>
            </div>
            <div className="fnl">
              <div>
                <div className="fnltop">
                  <b>{counts.total} ingested</b>
                  <span>all patients</span>
                </div>
                <div className="bar">
                  <div className="barfill" style={{ width: "100%" }} />
                </div>
              </div>
              <div>
                <div className="fnltop">
                  <b>{mcbCount} Medicare Part B</b>
                  <span>
                    {mcbPct}% · billable payer
                  </span>
                </div>
                <div className="bar">
                  <div className="barfill" style={{ width: `${mcbPct}%` }} />
                </div>
              </div>
              <div>
                <div className="fnltop">
                  <b>Routing decision</b>
                  <span>{counts.total} in queue</span>
                </div>
                <div className="bar">
                  <div className="seg acc" style={{ width: `${seg(counts.accept)}%` }} />
                  <div className="seg flag" style={{ width: `${seg(counts.flag)}%` }} />
                  <div className="seg rej" style={{ width: `${seg(counts.reject)}%` }} />
                </div>
                <div className="leg">
                  <span>
                    <i style={{ background: "var(--acc-fg)" }} />
                    Accept {counts.accept}
                  </span>
                  <span>
                    <i style={{ background: "var(--flag-fg)" }} />
                    Flag {counts.flag}
                  </span>
                  <span>
                    <i style={{ background: "var(--rej-fg)" }} />
                    Reject {counts.reject}
                  </span>
                </div>
              </div>
            </div>
          </div>
          <div className="card">
            <div className="cardhd">
              <div className="cardttl">Why cases get flagged</div>
              <div className="cardnote">top reasons</div>
            </div>
            <div className="lb">
              {flagReasons.length === 0 && <div className="muted">No flagged cases</div>}
              {flagReasons.map((f) => (
                <div key={f.label} className="lbrow">
                  <div className="lbtop">
                    <span>{f.label}</span>
                    <b>{f.count}</b>
                  </div>
                  <div className="lbtrack">
                    <div className="lbfill" style={{ width: `${f.width}%` }} />
                  </div>
                </div>
              ))}
            </div>
          </div>
          <div className="card">
            <div className="cardhd">
              <div className="cardttl">By facility</div>
              <div className="cardnote">decision mix</div>
            </div>
            <div className="fac">
              {facs.map((c) => (
                <div key={c.name} className="facrow">
                  <div className="factop">
                    <b>{c.name}</b>
                    <span>{c.total} patients</span>
                  </div>
                  <div className="bar">
                    <div className="seg acc" style={{ width: `${c.accW}%` }} />
                    <div className="seg flag" style={{ width: `${c.flagW}%` }} />
                    <div className="seg rej" style={{ width: `${c.rejW}%` }} />
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
      {!insights && (
        <div style={{ marginBottom: 14 }}>
          <button type="button" className="linkb" onClick={() => setInsights(true)}>
            Show insights
          </button>
        </div>
      )}

      <div className="queue">
        <div className="qhd">
          <div className="tabs">
            {(
              [
                ["all", "All", tabCounts.all],
                ["flag", "Needs action", tabCounts.flag],
                ["accept", "Auto-accept", tabCounts.accept],
                ["reject", "Rejects", tabCounts.reject],
              ] as const
            ).map(([k, label, n]) => (
              <button
                key={k}
                type="button"
                className={`tab${tab === k ? " on" : ""}`}
                onClick={() => setTab(k)}
              >
                {label} <span className="tcount">{n}</span>
              </button>
            ))}
          </div>
          <div className="qfilters">
            <select className="sel" value={fWound} onChange={(e) => setFWound(e.target.value)}>
              <option value="all">All wound types</option>
              {WOUND_TYPES.map((w) => (
                <option key={w} value={w}>
                  {w.replace(/\b\w/g, (c) => c.toUpperCase())}
                </option>
              ))}
            </select>
            <select className="sel" value={fFac} onChange={(e) => setFFac(e.target.value)}>
              <option value="all">All facilities</option>
              <option value="A">Facility A</option>
              <option value="B">Facility B</option>
              <option value="C">Facility C</option>
            </select>
            <select className="sel" value={fConf} onChange={(e) => setFConf(e.target.value)}>
              <option value="all">Any confidence</option>
              <option value="high">High (85%+)</option>
              <option value="med">Medium (70–85%)</option>
              <option value="low">Low (&lt;70%)</option>
            </select>
          </div>
        </div>

        {sel.length > 0 && (
          <div className="bulk">
            <b>{sel.length} selected</b>
            <span>Apply to all:</span>
            <button type="button" className="linkb" onClick={() => bulkStatus("submitted")}>
              ✓ Accept &amp; bill
            </button>
            <button type="button" className="linkb" onClick={() => bulkStatus("reviewed")}>
              ▲ Mark reviewed
            </button>
            <button type="button" className="linkb" onClick={() => bulkStatus("dismissed")}>
              ✕ Dismiss
            </button>
            <div className="spacer" />
            <button type="button" className="linkb" onClick={() => setSel([])}>
              Clear
            </button>
          </div>
        )}

        <div className="qrow qhead">
          <div className="th">
            <input
              type="checkbox"
              className="ckbx"
              checked={allSel}
              onChange={(e) => {
                if (e.target.checked) setSel(Array.from(new Set([...sel, ...visIds])));
                else setSel(sel.filter((id) => !visIds.includes(id)));
              }}
            />
          </div>
          <button type="button" className="th pointer" onClick={() => sort("name")}>
            Patient <span className="sortarw">{sortArrow("name")}</span>
          </button>
          <button type="button" className="th pointer" onClick={() => sort("sev")}>
            Wound <span className="sortarw">{sortArrow("sev")}</span>
          </button>
          <button type="button" className="th pointer" onClick={() => sort("decision")}>
            Decision <span className="sortarw">{sortArrow("decision")}</span>
          </button>
          <button type="button" className="th pointer" onClick={() => sort("conf")}>
            Signal <span className="sortarw">{sortArrow("conf")}</span>
          </button>
          <div className="th">Why</div>
          <div className="th">Action</div>
        </div>

        {filtered.map((r) => {
          const dc = toUiDecision(r.routing_decision);
          const conf = confidencePct(r);
          return (
            <div
              key={r.patient_id}
              className={`qrow tr ${dc}`}
              onClick={() => setModalId(r.patient_id)}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => e.key === "Enter" && setModalId(r.patient_id)}
            >
              <div
                className="cell"
                onClick={(e) => e.stopPropagation()}
                onKeyDown={(e) => e.stopPropagation()}
              >
                <input
                  type="checkbox"
                  className="ckbx"
                  checked={sel.includes(r.patient_id)}
                  onChange={() =>
                    setSel((s) =>
                      s.includes(r.patient_id)
                        ? s.filter((x) => x !== r.patient_id)
                        : [...s, r.patient_id],
                    )
                  }
                />
              </div>
              <div className="cell">
                <div className="patname">{patientName(r)}</div>
                <div className="patmeta mono">
                  {r.patient_id} · Fac {facilityLetter(r.facility_id)}
                  {r.status !== "pending" ? ` · ${r.status}` : ""}
                </div>
              </div>
              <div className="cell">
                <div className="woundttl">{woundTitle(r)}</div>
                <div className="woundsub">{woundSubtitle(r)}</div>
              </div>
              <div className="cell">
                <span className={`badge ${dc}`} title={TIP[dc]}>
                  <span className="bglyph">{GLYPH[dc]}</span>
                  {LABEL[dc]}
                </span>
              </div>
              <div className="cell sig">
                <div className="conftrack">
                  <div className="conffill" style={{ width: `${conf}%` }} />
                </div>
                <div className="sigrow">
                  <span className="conflab mono">{conf}%</span>
                  <svg className="spark" viewBox="0 0 60 20" preserveAspectRatio="none">
                    <polyline
                      points={sparkPoints(r)}
                      fill="none"
                      stroke="var(--accent)"
                      strokeWidth="2"
                      strokeLinejoin="round"
                      strokeLinecap="round"
                    />
                  </svg>
                </div>
              </div>
              <div className="cell">
                <div className="reason">{r.reason}</div>
              </div>
              <div className="cell acts" onClick={(e) => e.stopPropagation()}>
                <button
                  type="button"
                  className={`abtn${dc === "accept" ? " abtn-acc-on" : ""}`}
                  title="Accept & bill"
                  onClick={() => setStatus(r.patient_id, "submitted")}
                >
                  ✓
                </button>
                <button
                  type="button"
                  className={`abtn${dc === "flag" ? " abtn-flag-on" : ""}`}
                  title="Mark reviewed"
                  onClick={() => setStatus(r.patient_id, "reviewed")}
                >
                  ▲
                </button>
                <button
                  type="button"
                  className={`abtn${dc === "reject" ? " abtn-rej-on" : ""}`}
                  title="Dismiss"
                  onClick={() => setStatus(r.patient_id, "dismissed")}
                >
                  ✕
                </button>
              </div>
            </div>
          );
        })}
        {filtered.length === 0 && <div className="empty">No patients match these filters.</div>}
      </div>

      <div className="foot">
        OuchLess · ABI Frameworks × Pulse Foundry AI NYC · live triage data from the pipeline.
        Decisions are advisory — a biller confirms before submitting to Medicare.
      </div>

      {modalRow && (
        <PatientModal row={modalRow} onClose={() => setModalId(null)} onStatus={setStatus} />
      )}
    </>
  );
}
