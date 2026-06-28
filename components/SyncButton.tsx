"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

export default function SyncButton() {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  async function sync() {
    setBusy(true);
    setMsg(null);
    try {
      const res = await fetch("/api/sync", { method: "POST" });
      const j = await res.json();
      if (!res.ok) throw new Error(j.error ?? "failed");
      setMsg(
        `Synced: ${j.deltaPatients} changed patient(s) fetched, ${j.untouched} untouched. Watermark ${j.watermark ?? "—"}.`,
      );
      router.refresh();
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <span style={{ display: "inline-flex", gap: "0.5rem", alignItems: "center" }}>
      <button className="btn" onClick={sync} disabled={busy}>
        {busy ? "Syncing…" : "Sync (incremental)"}
      </button>
      {msg && <span className="muted" style={{ fontSize: "0.8rem" }}>{msg}</span>}
    </span>
  );
}
