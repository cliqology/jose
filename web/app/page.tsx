import Link from "next/link";
import { StatCard } from "@/components/stat-card";
import { getDashboardSummary, getJobs, getSources } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function DashboardPage() {
  try {
    const [summary, jobs, sources] = await Promise.all([
      getDashboardSummary(),
      getJobs(),
      getSources(),
    ]);
    const failing = sources.filter((source) => source.last_error).slice(0, 5);
    const recentJobs = jobs.slice(0, 6);

    return (
      <>
        <section className="hero">
          <div>
            <p className="eyebrow">Phase 0 / 1 foundation</p>
            <h1>Your job-search control room.</h1>
            <p>
              JOSE is collecting, normalizing, and tracking opportunities. Scoring and
              application preparation arrive in the next phase.
            </p>
          </div>
          <div className="heroBadge">Human approved. Cloud ready.</div>
        </section>

        <section className="statGrid" aria-label="System summary">
          <StatCard label="Sources" value={summary.sources_total} detail={`${summary.sources_enabled} enabled`} />
          <StatCard label="Jobs" value={summary.jobs_total} detail={`${summary.jobs_seen_last_24h} new in 24 hours`} />
          <StatCard label="Queued work" value={summary.queued_tasks} detail={`${summary.running_tasks} running`} />
          <StatCard label="Source failures" value={summary.sources_failing} warning={summary.sources_failing > 0} detail="Failures are visible, never hidden" />
          <StatCard label="Changed" value={summary.jobs_changed_last_24h} detail="in the last 24 hours" />
          <StatCard label="Removed" value={summary.jobs_removed_last_24h} detail="in the last 24 hours" />
          <StatCard label="Reposted" value={summary.jobs_reposted_last_24h} detail="in the last 24 hours" />
        </section>

        <section className="twoColumn">
          <article className="panel">
            <div className="panelHeader">
              <div>
                <p className="eyebrow">Recently discovered</p>
                <h2>Jobs</h2>
              </div>
              <Link href="/jobs">View all</Link>
            </div>
            {recentJobs.length ? (
              <div className="list">
                {recentJobs.map((job) => (
                  <a className="listRow" href={job.application_url} key={job.id} rel="noreferrer" target="_blank">
                    <span>
                      <strong>{job.title}</strong>
                      <small>{job.company_name} · {job.location ?? "Location not listed"}</small>
                    </span>
                    <em>{job.ats_type ?? "web"}</em>
                  </a>
                ))}
              </div>
            ) : (
              <EmptyState text="Import sources and run collection to populate this list." />
            )}
          </article>

          <article className="panel">
            <div className="panelHeader">
              <div>
                <p className="eyebrow">Needs attention</p>
                <h2>Source health</h2>
              </div>
              <Link href="/sources">View sources</Link>
            </div>
            {failing.length ? (
              <div className="list">
                {failing.map((source) => (
                  <div className="listRow errorRow" key={source.id}>
                    <span>
                      <strong>{source.name}</strong>
                      <small>{source.last_error}</small>
                    </span>
                    <em>{source.adapter}</em>
                  </div>
                ))}
              </div>
            ) : (
              <EmptyState text="No source failures have been recorded." />
            )}
          </article>
        </section>
      </>
    );
  } catch (error) {
    return <ApiUnavailable error={error} />;
  }
}

function EmptyState({ text }: { text: string }) {
  return <p className="emptyState">{text}</p>;
}

function ApiUnavailable({ error }: { error: unknown }) {
  return (
    <section className="panel apiError">
      <p className="eyebrow">JOSE API unavailable</p>
      <h1>The dashboard cannot reach the backend.</h1>
      <p>Start the Docker environment with <code>make dev</code>, then refresh this page.</p>
      <pre>{error instanceof Error ? error.message : "Unknown error"}</pre>
    </section>
  );
}
