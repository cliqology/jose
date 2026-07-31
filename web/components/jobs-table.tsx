"use client";

import Link from "next/link";
import { useState } from "react";
import type { Job } from "@/lib/api";
import { JobDecisionControls } from "@/components/job-decision-controls";

function formatDate(value: string | null): string {
  return value ? new Date(value).toLocaleDateString() : "Unknown";
}

export function JobsTable({ initialJobs }: { initialJobs: Job[] }) {
  const [jobs, setJobs] = useState(initialJobs);

  function updateDecision(jobId: string, decision: string | null) {
    setJobs((current) =>
      current.map((job) => (job.id === jobId ? { ...job, user_decision: decision } : job)),
    );
  }

  if (!jobs.length) {
    return <p className="emptyState">No jobs match the current filters.</p>;
  }

  return (
    <div className="tableWrap">
      <table>
        <thead>
          <tr>
            <th>Company</th>
            <th>Title</th>
            <th>Location</th>
            <th>ATS</th>
            <th>First seen</th>
            <th>Decision</th>
          </tr>
        </thead>
        <tbody>
          {jobs.map((job) => (
            <tr key={job.id}>
              <td>{job.company_name}</td>
              <td>
                <Link href={`/jobs/${job.id}`}>{job.title}</Link>
              </td>
              <td>{job.location ?? "Location not listed"}</td>
              <td>
                <code>{job.ats_type ?? "web"}</code>
              </td>
              <td>{formatDate(job.first_seen_at)}</td>
              <td>
                <JobDecisionControls
                  jobId={job.id}
                  decision={job.user_decision}
                  onChange={(decision) => updateDecision(job.id, decision)}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
