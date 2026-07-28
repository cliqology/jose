import Link from "next/link";
import { ImportManager } from "@/components/import-manager";
import { getImportRuns } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function SourceImportPage() {
  const runs = await getImportRuns();
  return (
    <section>
      <div className="pageHeader">
        <div>
          <p className="eyebrow">Collection registry</p>
          <h1>Import sources</h1>
          <p>Upload the VC job-search workbook and review changes before they apply.</p>
        </div>
        <Link className="primaryAction ghostButton" href="/sources">
          Back to sources
        </Link>
      </div>

      <ImportManager initialRuns={runs} />
    </section>
  );
}
