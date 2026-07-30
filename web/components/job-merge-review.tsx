"use client";

import { useState } from "react";
import type { JobMergeCandidate } from "@/lib/api";
import { apiFetchJson } from "@/lib/browser-api";

function formatScore(value: number): string {
  return `${Math.round(value * 100)}%`;
}

export function JobMergeReview({
  initialCandidates,
}: {
  initialCandidates: JobMergeCandidate[];
}) {
  const [candidates, setCandidates] = useState(initialCandidates);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function resolve(candidateId: string, body: Record<string, unknown>) {
    setError(null);
    setBusyId(candidateId);
    try {
      await apiFetchJson(`/api/v1/job-merge-candidates/${candidateId}/resolve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      setCandidates((current) => current.filter((c) => c.id !== candidateId));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Action failed");
    } finally {
      setBusyId(null);
    }
  }

  if (!candidates.length) {
    return <p className="emptyState">No potential duplicates waiting for review.</p>;
  }

  return (
    <>
      {error ? <p className="formError">{error}</p> : null}
      <div className="tableWrap">
        <table>
          <thead>
            <tr>
              <th>Job</th>
              <th>Possible duplicate</th>
              <th>Match</th>
              <th aria-label="Actions" />
            </tr>
          </thead>
          <tbody>
            {candidates.map((candidate) => (
              <tr key={candidate.id}>
                <td>
                  <strong>{candidate.job.title}</strong>
                  <small>
                    {candidate.job.company_name} —{" "}
                    {candidate.job.location ?? "Location not listed"}
                  </small>
                </td>
                <td>
                  <strong>{candidate.candidate_job.title}</strong>
                  <small>
                    {candidate.candidate_job.company_name} —{" "}
                    {candidate.candidate_job.location ?? "Location not listed"}
                  </small>
                </td>
                <td>
                  <span>{formatScore(candidate.similarity_score)} overall</span>
                  <small>
                    company {formatScore(candidate.matched_signals.company)}, title{" "}
                    {formatScore(candidate.matched_signals.title)}, location{" "}
                    {formatScore(candidate.matched_signals.location)}
                  </small>
                </td>
                <td>
                  <div className="rowActions">
                    <button
                      type="button"
                      disabled={busyId === candidate.id}
                      onClick={() => resolve(candidate.id, { action: "merge", keep: "job" })}
                    >
                      Keep first, merge
                    </button>
                    <button
                      type="button"
                      disabled={busyId === candidate.id}
                      onClick={() =>
                        resolve(candidate.id, { action: "merge", keep: "candidate" })
                      }
                    >
                      Keep second, merge
                    </button>
                    <button
                      type="button"
                      className="ghostButton"
                      disabled={busyId === candidate.id}
                      onClick={() => resolve(candidate.id, { action: "dismiss" })}
                    >
                      Not a duplicate
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
