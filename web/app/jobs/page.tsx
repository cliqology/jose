import Link from "next/link";
import { getJobs } from "@/lib/api";

export const dynamic = "force-dynamic";

function formatDate(value: string | null): string {
  return value ? new Date(value).toLocaleDateString() : "Unknown";
}

export default async function JobsPage() {
  const jobs = await getJobs();
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

      <div className="jobGrid">
        {jobs.map((job) => (
          <article className="jobCard" key={job.id}>
            <div className="jobMeta">
              <span>{job.ats_type ?? "web"}</span>
              <span>{formatDate(job.published_at ?? job.first_seen_at)}</span>
            </div>
            <h2>{job.title}</h2>
            <p className="company">{job.company_name}</p>
            <p>{job.location ?? "Location not listed"}</p>
            <a className="primaryAction" href={job.application_url} rel="noreferrer" target="_blank">
              Open original posting
            </a>
          </article>
        ))}
      </div>
      {!jobs.length ? <p className="emptyState">No jobs have been collected yet.</p> : null}
    </section>
  );
}
