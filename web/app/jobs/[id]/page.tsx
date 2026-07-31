import Link from "next/link";
import { revalidatePath } from "next/cache";
import { JobDecisionControls } from "@/components/job-decision-controls";
import { getJob } from "@/lib/api";

export const dynamic = "force-dynamic";

function formatDate(value: string | null): string {
  return value ? new Date(value).toLocaleString() : "Unknown";
}

export default async function JobDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;

  // JobDecisionControls is a Client Component; only Server Actions (not plain
  // closures) may cross the Server -> Client boundary as function props.
  // Revalidating this route makes the decision buttons re-render with the
  // freshly persisted value after a click, since this page holds no client
  // state of its own.
  async function refreshJobDecision() {
    "use server";
    revalidatePath(`/jobs/${id}`);
  }

  try {
    const job = await getJob(id);

    return (
      <section>
        <div className="pageHeader">
          <div>
            <p className="eyebrow">{job.company_name}</p>
            <h1>{job.title}</h1>
            <p>{job.location ?? "Location not listed"}</p>
          </div>
          <div className="rowActions">
            <a
              className="primaryAction"
              href={job.application_url}
              rel="noreferrer"
              target="_blank"
            >
              Open original posting
            </a>
            <Link className="ghostButton" href="/jobs">
              Back to jobs
            </Link>
          </div>
        </div>

        <div className="panel" style={{ marginBottom: "1.5rem" }}>
          <div className="panelHeader">
            <h2>Your decision</h2>
          </div>
          <JobDecisionControls jobId={job.id} decision={job.user_decision} onChange={refreshJobDecision} />
        </div>

        <dl className="kvGrid">
          <div className="kvItem">
            <dt>ATS</dt>
            <dd>
              <code>{job.ats_type ?? "web"}</code>
            </dd>
          </div>
          <div className="kvItem">
            <dt>First seen</dt>
            <dd>{formatDate(job.first_seen_at)}</dd>
          </div>
          <div className="kvItem">
            <dt>Last seen</dt>
            <dd>{formatDate(job.last_seen_at)}</dd>
          </div>
        </dl>

        <div className="panel" style={{ marginBottom: "1.5rem" }}>
          <div className="panelHeader">
            <h2>Description</h2>
          </div>
          {job.description_text ? (
            <pre style={{ whiteSpace: "pre-wrap" }}>{job.description_text}</pre>
          ) : (
            <p className="emptyState">No description captured for this job.</p>
          )}
        </div>

        <div className="panel" style={{ marginBottom: "1.5rem" }}>
          <div className="panelHeader">
            <h2>Source lineage</h2>
            <span className="countPill">{job.sources.length} sources</span>
          </div>
          {job.sources.length === 0 ? (
            <p className="emptyState">No source lineage recorded.</p>
          ) : (
            <div className="tableWrap">
              <table>
                <thead>
                  <tr>
                    <th>Source</th>
                    <th>Category</th>
                    <th>Status</th>
                    <th>First seen</th>
                    <th>Last seen</th>
                  </tr>
                </thead>
                <tbody>
                  {job.sources.map((source) => (
                    <tr key={source.source_id}>
                      <td>
                        {source.source_job_url ? (
                          <a href={source.source_job_url} rel="noreferrer" target="_blank">
                            {source.source_name}
                          </a>
                        ) : (
                          source.source_name
                        )}
                      </td>
                      <td>{source.source_category.replaceAll("_", " ")}</td>
                      <td>
                        {source.is_active ? (
                          <span className="status good">Active</span>
                        ) : (
                          <span className="status neutral">Inactive</span>
                        )}
                      </td>
                      <td>{formatDate(source.first_seen_at)}</td>
                      <td>{formatDate(source.last_seen_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <div className="panel">
          <div className="panelHeader">
            <h2>Version history</h2>
            <span className="countPill">{job.versions.length} versions</span>
          </div>
          {job.versions.length === 0 ? (
            <p className="emptyState">No version history recorded.</p>
          ) : (
            <div className="tableWrap">
              <table>
                <thead>
                  <tr>
                    <th>Seen</th>
                    <th>Change type</th>
                  </tr>
                </thead>
                <tbody>
                  {job.versions.map((version) => (
                    <tr key={version.content_hash}>
                      <td>{formatDate(version.seen_at)}</td>
                      <td>
                        {version.is_material ? (
                          <span className="status warn">Material change</span>
                        ) : (
                          <span className="status neutral">Formatting only</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </section>
    );
  } catch (error) {
    return (
      <section className="panel apiError">
        <p className="eyebrow">Job unavailable</p>
        <h1>This job could not be loaded.</h1>
        <p>
          It may not exist, or the JOSE API may be unreachable. <Link href="/jobs">Back to jobs</Link>.
        </p>
        <pre>{error instanceof Error ? error.message : "Unknown error"}</pre>
      </section>
    );
  }
}
