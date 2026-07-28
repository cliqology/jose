import Link from "next/link";
import { SourceManager } from "@/components/source-manager";
import { getSources } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function SourcesPage() {
  const sources = await getSources();
  return (
    <section>
      <div className="pageHeader">
        <div>
          <p className="eyebrow">Collection registry</p>
          <h1>Sources</h1>
          <p>Every board, newsletter, and network JOSE knows about.</p>
        </div>
        <div className="rowActions">
          <Link className="primaryAction ghostButton" href="/sources/import">
            Import from spreadsheet
          </Link>
          <span className="countPill">{sources.length} sources</span>
        </div>
      </div>

      <SourceManager initialSources={sources} />
    </section>
  );
}
