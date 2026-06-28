import { getAllTriage } from "@/lib/supabase/queries";
import TriageDashboard from "@/components/TriageDashboard";

export const dynamic = "force-dynamic";

export default async function Home() {
  let rows;
  try {
    rows = await getAllTriage();
  } catch (e) {
    return (
      <div>
        <h1 className="h1">Triage Queue</h1>
        <p className="sub">Could not load triage data: {e instanceof Error ? e.message : String(e)}</p>
        <p className="muted">Run `npm run extract` to populate the triage table, then refresh.</p>
      </div>
    );
  }

  if (rows.length === 0) {
    return (
      <div>
        <h1 className="h1">Triage Queue</h1>
        <p className="sub">No triage rows yet — run `npm run extract` to populate them.</p>
      </div>
    );
  }

  const mcbCount = rows.filter((r) => r.has_active_mcb).length;

  return <TriageDashboard rows={rows} mcbCount={mcbCount} />;
}
