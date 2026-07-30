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
  status: "success" | "failed" | "running";
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
  user_decision: string | null;
};

export type JobFilters = {
  company?: string;
  title?: string;
  source_id?: string;
  date_from?: string;
  date_to?: string;
  location?: string;
  ats_type?: string;
  status?: string;
  decision?: string[];
  limit?: number;
  offset?: number;
};

export type JobSourceLineage = {
  source_id: string;
  source_name: string;
  source_category: string;
  source_job_url: string | null;
  is_active: boolean;
  first_seen_at: string;
  last_seen_at: string;
};

export type JobVersionEntry = {
  seen_at: string;
  is_material: boolean;
  content_hash: string;
};

export type JobDetail = Job & {
  normalized_title: string;
  description_text: string | null;
  department: string | null;
  remote_type: string | null;
  employment_type: string | null;
  compensation_min: number | null;
  compensation_max: number | null;
  currency: string | null;
  canonical_url: string;
  sources: JobSourceLineage[];
  versions: JobVersionEntry[];
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

function buildJobsQuery(filters: JobFilters): string {
  const params = new URLSearchParams();
  if (filters.company) params.set("company", filters.company);
  if (filters.title) params.set("title", filters.title);
  if (filters.source_id) params.set("source_id", filters.source_id);
  if (filters.date_from) params.set("date_from", filters.date_from);
  if (filters.date_to) params.set("date_to", filters.date_to);
  if (filters.location) params.set("location", filters.location);
  if (filters.ats_type) params.set("ats_type", filters.ats_type);
  if (filters.status) params.set("status", filters.status);
  for (const decision of filters.decision ?? []) {
    params.append("decision", decision);
  }
  params.set("limit", String(filters.limit ?? 50));
  params.set("offset", String(filters.offset ?? 0));
  return params.toString();
}

export async function getJobs(filters: JobFilters = {}): Promise<Job[]> {
  return getJson<Job[]>(`/api/v1/jobs?${buildJobsQuery(filters)}`);
}

export async function getJob(id: string): Promise<JobDetail> {
  return getJson<JobDetail>(`/api/v1/jobs/${id}`);
}

export async function getJobMergeCandidates(): Promise<JobMergeCandidate[]> {
  return getJson<JobMergeCandidate[]>("/api/v1/job-merge-candidates?status=pending");
}

export async function getImportRuns(): Promise<ImportRun[]> {
  return getJson<ImportRun[]>("/api/v1/sources/import/runs");
}
