import Link from "next/link";
import { CollectButton } from "@/components/collect-button";
import { SourceRunHistory } from "@/components/source-run-history";
import { getSource, getSourceRuns } from "@/lib/api";

export const dynamic = "force-dynamic";

function formatDate(value: string | null): string {
  return value ? new Date(value).toLocaleString() : "Never";
}

export default async function SourceDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;

  try {
    const [source, runs] = await Promise.all([getSource(id), getSourceRuns(id)]);
    const lastRun = runs[0] ?? null;
    const lastRunDuration =
      lastRun && lastRun.completed_at
        ? `${Math.max(
            0,
            Math.round(
              (new Date(lastRun.completed_at).getTime() -
                new Date(lastRun.started_at).getTime()) /
                1000,
            ),
          )}s`
        : "—";

    return (
      <section>
        <div className="pageHeader">
          <div>
            <p className="eyebrow">{source.category.replaceAll("_", " ")}</p>
            <h1>{source.name}</h1>
            <p>
              <a href={source.url} rel="noreferrer" target="_blank">
                {source.url}
              </a>
            </p>
          </div>
          <div className="rowActions">
            {source.enabled ? <CollectButton sourceId={source.id} /> : null}
            <Link className="ghostButton" href="/sources">
              Back to sources
            </Link>
          </div>
        </div>

        {source.consecutive_failures >= 2 ? (
          <p className="warningBanner">
            {source.consecutive_failures} failed runs in a row. Check the adapter or URL below.
          </p>
        ) : null}

        <dl className="kvGrid">
          <div className="kvItem">
            <dt>Last attempt</dt>
            <dd>{formatDate(source.last_attempt_at)}</dd>
          </div>
          <div className="kvItem">
            <dt>Last success</dt>
            <dd>{formatDate(source.last_success_at)}</dd>
          </div>
          <div className="kvItem">
            <dt>Last run duration</dt>
            <dd>{lastRunDuration}</dd>
          </div>
          <div className="kvItem">
            <dt>Last job count</dt>
            <dd>{source.last_job_count ?? "—"}</dd>
          </div>
          <div className="kvItem">
            <dt>Adapter</dt>
            <dd>
              <code>{source.adapter}</code>
            </dd>
          </div>
          <div className={`kvItem${source.last_error ? " warning" : ""}`}>
            <dt>Current error</dt>
            <dd>{source.last_error ?? "None"}</dd>
          </div>
        </dl>

        <div className="panel">
          <div className="panelHeader">
            <h2>Run history</h2>
            <span className="countPill">{runs.length} recent runs</span>
          </div>
          <SourceRunHistory runs={runs} />
        </div>
      </section>
    );
  } catch (error) {
    return (
      <section className="panel apiError">
        <p className="eyebrow">Source unavailable</p>
        <h1>This source could not be loaded.</h1>
        <p>
          It may not exist, or the JOSE API may be unreachable. <Link href="/sources">Back to sources</Link>.
        </p>
        <pre>{error instanceof Error ? error.message : "Unknown error"}</pre>
      </section>
    );
  }
}
