export type DashboardSummary = {
  sources_total: number;
  sources_enabled: number;
  sources_failing: number;
  jobs_total: number;
  jobs_seen_last_24h: number;
  jobs_new_last_24h: number;
  jobs_changed_last_24h: number;
  jobs_removed_last_24h: number;
  jobs_reposted_last_24h: number;
  queued_tasks: number;
  running_tasks: number;
};

export type Source = {
  id: string;
  name: string;
  url: string;
  category: string;
  portfolio_firm: string | null;
  adapter: string;
  enabled: boolean;
  priority: number;
  collection_frequency: string;
  last_attempt_at: string | null;
  last_success_at: string | null;
  last_job_count: number | null;
  last_error: string | null;
  consecutive_failures: number;
};

export type SourceRun = {
  id: string;
  status: string;
  started_at: string;
  completed_at: string | null;
  jobs_found: number;
  jobs_created: number;
  jobs_updated: number;
  jobs_rejected: number;
  error_type: string | null;
  error_message: string | null;
};

export type Job = {
  id: string;
  company_name: string;
  title: string;
  location: string | null;
  application_url: string;
  ats_type: string | null;
  published_at: string | null;
  first_seen_at: string;
  last_seen_at: string;
  status: string;
};

export type JobMergeSummary = {
  id: string;
  title: string;
  company_name: string;
  location: string | null;
  application_url: string;
  status: string;
};

export type JobMergeCandidate = {
  id: string;
  status: string;
  similarity_score: number;
  matched_signals: { company: number; title: number; location: number };
  created_at: string;
  job: JobMergeSummary;
  candidate_job: JobMergeSummary;
};

export type ImportRun = {
  id: string;
  filename: string;
  created_count: number;
  updated_count: number;
  skipped_count: number;
  flagged_count: number;
  flagged_rows: { row_number: number; name: string; url: string; reason: string | null }[];
  completed_at: string;
};

function apiBaseUrl(): string {
  return (
    process.env.JOSE_INTERNAL_API_BASE_URL ??
    process.env.NEXT_PUBLIC_API_BASE_URL ??
    "http://localhost:8000"
  );
}

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${apiBaseUrl()}${path}`, {
    cache: "no-store",
    signal: AbortSignal.timeout(10_000),
  });
  if (!response.ok) {
    throw new Error(`JOSE API returned ${response.status} for ${path}`);
  }
  return (await response.json()) as T;
}

export async function getDashboardSummary(): Promise<DashboardSummary> {
  return getJson<DashboardSummary>("/api/v1/dashboard/summary");
}

export async function getSources(): Promise<Source[]> {
  return getJson<Source[]>("/api/v1/sources");
}

export async function getSource(id: string): Promise<Source> {
  return getJson<Source>(`/api/v1/sources/${id}`);
}

export async function getSourceRuns(id: string): Promise<SourceRun[]> {
  return getJson<SourceRun[]>(`/api/v1/sources/${id}/runs`);
}

export async function getJobs(): Promise<Job[]> {
  return getJson<Job[]>("/api/v1/jobs?limit=200");
}

export async function getJobMergeCandidates(): Promise<JobMergeCandidate[]> {
  return getJson<JobMergeCandidate[]>("/api/v1/job-merge-candidates?status=pending");
}

export async function getImportRuns(): Promise<ImportRun[]> {
  return getJson<ImportRun[]>("/api/v1/sources/import/runs");
}
