import Link from "next/link";
import { JobFilters } from "@/components/job-filters";
import { JobsTable } from "@/components/jobs-table";
import { getJobs, getSources } from "@/lib/api";
import type { JobFilters as JobFiltersType } from "@/lib/api";

export const dynamic = "force-dynamic";

const PAGE_SIZE = 50;

type RawSearchParams = Record<string, string | string[] | undefined>;

function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

function toFilters(searchParams: RawSearchParams): JobFiltersType {
  const decision = first(searchParams.decision);
  const offset = first(searchParams.offset);
  return {
    company: first(searchParams.company),
    title: first(searchParams.title),
    source_id: first(searchParams.source_id),
    date_from: first(searchParams.date_from),
    date_to: first(searchParams.date_to),
    location: first(searchParams.location),
    ats_type: first(searchParams.ats_type),
    status: first(searchParams.status),
    decision: decision ? [decision] : undefined,
    limit: PAGE_SIZE,
    offset: offset ? Number(offset) : 0,
  };
}

function pageHref(searchParams: RawSearchParams, offset: number): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(searchParams)) {
    if (key === "offset" || typeof value !== "string") continue;
    params.set(key, value);
  }
  if (offset > 0) params.set("offset", String(offset));
  const query = params.toString();
  return query ? `/jobs?${query}` : "/jobs";
}

function searchParamsKey(searchParams: RawSearchParams): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(searchParams)) {
    if (value === undefined) continue;
    for (const entry of Array.isArray(value) ? value : [value]) {
      params.append(key, entry);
    }
  }
  params.sort();
  return params.toString();
}

export default async function JobsPage({
  searchParams,
}: {
  searchParams: Promise<RawSearchParams>;
}) {
  const resolvedSearchParams = await searchParams;
  const filters = toFilters(resolvedSearchParams);
  const offset = filters.offset ?? 0;

  try {
    const [jobs, sources] = await Promise.all([getJobs(filters), getSources()]);

    return (
      <section>
        <div className="pageHeader">
          <div>
            <p className="eyebrow">Normalized opportunities</p>
            <h1>Jobs</h1>
            <p>One canonical record per opportunity, even when several sources find it.</p>
          </div>
          <div className="rowActions">
            <Link className="primaryAction ghostButton" href="/jobs/review">
              Review possible duplicates
            </Link>
            <span className="countPill">{jobs.length} shown</span>
          </div>
        </div>

        <JobFilters sources={sources.map((source) => ({ id: source.id, name: source.name }))} />

        <JobsTable key={searchParamsKey(resolvedSearchParams)} initialJobs={jobs} />

        <div className="rowActions" style={{ marginTop: "1rem" }}>
          {offset > 0 ? (
            <Link
              className="ghostButton"
              href={pageHref(resolvedSearchParams, Math.max(0, offset - PAGE_SIZE))}
            >
              Previous
            </Link>
          ) : null}
          {jobs.length === PAGE_SIZE ? (
            <Link
              className="ghostButton"
              href={pageHref(resolvedSearchParams, offset + PAGE_SIZE)}
            >
              Next
            </Link>
          ) : null}
        </div>
      </section>
    );
  } catch (error) {
    return (
      <section className="panel apiError">
        <p className="eyebrow">Jobs unavailable</p>
        <h1>Jobs could not be loaded.</h1>
        <p>The JOSE API may be unreachable, or a filter value may be invalid.</p>
        <pre>{error instanceof Error ? error.message : "Unknown error"}</pre>
      </section>
    );
  }
}
