import type { SourceRun } from "@/lib/api";

function formatDateTime(value: string): string {
  return new Date(value).toLocaleString();
}

export function formatDuration(run: SourceRun): string {
  if (!run.completed_at) return "—";
  const seconds = Math.max(
    0,
    Math.round(
      (new Date(run.completed_at).getTime() - new Date(run.started_at).getTime()) / 1000,
    ),
  );
  if (seconds < 60) return `${seconds}s`;
  return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
}

function RunStatus({ run }: { run: SourceRun }) {
  if (run.status === "failed") return <span className="status bad">Failed</span>;
  if (run.status === "running") return <span className="status neutral">Running</span>;
  if (run.jobs_found === 0) return <span className="status neutral">Success · 0 jobs</span>;
  return <span className="status good">Success</span>;
}

export function SourceRunHistory({ runs }: { runs: SourceRun[] }) {
  if (runs.length === 0) {
    return (
      <p className="emptyState">
        No runs recorded yet. Trigger a collection to see history here.
      </p>
    );
  }

  return (
    <div className="tableWrap">
      <table>
        <thead>
          <tr>
            <th>Status</th>
            <th>Started</th>
            <th>Duration</th>
            <th>Found</th>
            <th>Created</th>
            <th>Updated</th>
            <th>Rejected</th>
            <th>Error</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((run) => (
            <tr key={run.id}>
              <td>
                <RunStatus run={run} />
              </td>
              <td>{formatDateTime(run.started_at)}</td>
              <td>{formatDuration(run)}</td>
              <td>{run.jobs_found}</td>
              <td>{run.jobs_created}</td>
              <td>{run.jobs_updated}</td>
              <td>{run.jobs_rejected}</td>
              <td>
                {run.error_message ? (
                  <span title={run.error_message}>{run.error_type ?? "Error"}</span>
                ) : (
                  "—"
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
