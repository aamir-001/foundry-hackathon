import { getAllTriage } from "@/lib/supabase/queries";
import DataTable from "@/components/DataTable";

export const dynamic = "force-dynamic";

export default async function EligibilityPage() {
  const rows = await getAllTriage();
  return (
    <main className="wrap">
      <h1>3 · Eligibility output table</h1>
      <p className="sub">
        One row per patient: extracted wound fields · active Medicare Part B · routing decision · a
        plain-English reason. Filter by decision, search, or export to CSV.
      </p>
      <DataTable rows={rows} variant="eligibility" filename="eligibility.csv" filterable />
    </main>
  );
}
