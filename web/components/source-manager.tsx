"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import type { Source } from "@/lib/api";
import { apiFetch, apiFetchJson } from "@/lib/browser-api";
import { CollectButton } from "@/components/collect-button";

const CATEGORIES = [
  "vc_portfolio",
  "company_career_page",
  "ats_job_board",
  "newsletter",
  "talent_network",
  "user_added",
];

const ADAPTERS = ["auto", "ashby", "greenhouse", "lever", "jsonld", "unsupported"];

const FREQUENCIES = ["hourly", "every_6_hours", "twice_daily", "daily", "weekly", "manual"];

type FormValues = {
  name: string;
  url: string;
  category: string;
  portfolio_firm: string;
  adapter: string;
  priority: number;
  collection_frequency: string;
  notes: string;
};

const EMPTY_FORM: FormValues = {
  name: "",
  url: "",
  category: "user_added",
  portfolio_firm: "",
  adapter: "auto",
  priority: 100,
  collection_frequency: "daily",
  notes: "",
};

function toFormValues(source: Source): FormValues {
  return {
    name: source.name,
    url: source.url,
    category: source.category,
    portfolio_firm: source.portfolio_firm ?? "",
    adapter: source.adapter,
    priority: source.priority,
    collection_frequency: source.collection_frequency,
    notes: "",
  };
}

function toPayload(values: FormValues): Record<string, unknown> {
  return {
    name: values.name,
    url: values.url,
    category: values.category,
    portfolio_firm: values.portfolio_firm || null,
    adapter: values.adapter,
    priority: Number(values.priority),
    collection_frequency: values.collection_frequency,
    notes: values.notes || null,
  };
}

function SourceFormFields({
  values,
  onChange,
}: {
  values: FormValues;
  onChange: (next: FormValues) => void;
}) {
  return (
    <div className="sourceForm">
      <label>
        Name
        <input
          value={values.name}
          onChange={(event) => onChange({ ...values, name: event.target.value })}
          required
        />
      </label>
      <label>
        URL
        <input
          type="url"
          value={values.url}
          onChange={(event) => onChange({ ...values, url: event.target.value })}
          required
        />
      </label>
      <label>
        Category
        <select
          value={values.category}
          onChange={(event) => onChange({ ...values, category: event.target.value })}
        >
          {CATEGORIES.map((category) => (
            <option key={category} value={category}>
              {category.replaceAll("_", " ")}
            </option>
          ))}
        </select>
      </label>
      <label>
        Adapter
        <select
          value={values.adapter}
          onChange={(event) => onChange({ ...values, adapter: event.target.value })}
        >
          {ADAPTERS.map((adapter) => (
            <option key={adapter} value={adapter}>
              {adapter}
            </option>
          ))}
        </select>
      </label>
      <label>
        Priority
        <input
          type="number"
          min={1}
          max={1000}
          value={values.priority}
          onChange={(event) => onChange({ ...values, priority: Number(event.target.value) })}
        />
      </label>
      <label>
        Frequency
        <select
          value={values.collection_frequency}
          onChange={(event) =>
            onChange({ ...values, collection_frequency: event.target.value })
          }
        >
          {FREQUENCIES.map((frequency) => (
            <option key={frequency} value={frequency}>
              {frequency.replaceAll("_", " ")}
            </option>
          ))}
        </select>
      </label>
      <label>
        Portfolio firm
        <input
          value={values.portfolio_firm}
          onChange={(event) => onChange({ ...values, portfolio_firm: event.target.value })}
        />
      </label>
    </div>
  );
}

function formatDate(value: string | null): string {
  return value ? new Date(value).toLocaleString() : "Never";
}

type SourceStatus = "failed" | "enabled" | "disabled";

function getStatus(source: Source): SourceStatus {
  if (source.last_error) return "failed";
  return source.enabled ? "enabled" : "disabled";
}

const STATUS_LABELS: Record<SourceStatus, string> = {
  failed: "Failed",
  enabled: "Enabled",
  disabled: "Disabled",
};

type SortKey = "name" | "category" | "adapter" | "last_success_at" | "last_job_count" | "status";

const SORTABLE_COLUMNS: { key: SortKey; label: string }[] = [
  { key: "name", label: "Source" },
  { key: "category", label: "Category" },
  { key: "adapter", label: "Adapter" },
  { key: "last_success_at", label: "Last success" },
  { key: "last_job_count", label: "Jobs" },
  { key: "status", label: "Status" },
];

function getSortValue(source: Source, key: SortKey): string | number | null {
  switch (key) {
    case "name":
      return source.name.toLowerCase();
    case "category":
      return source.category;
    case "adapter":
      return source.adapter;
    case "last_success_at":
      return source.last_success_at ? new Date(source.last_success_at).getTime() : null;
    case "last_job_count":
      return source.last_job_count;
    case "status":
      return getStatus(source);
  }
}

function compareSortValues(a: string | number | null, b: string | number | null): number {
  // Nulls (never collected, unknown job count) always sort last, regardless of direction.
  if (a === null && b === null) return 0;
  if (a === null) return 1;
  if (b === null) return -1;
  if (typeof a === "number" && typeof b === "number") return a - b;
  return String(a).localeCompare(String(b));
}

export function SourceManager({ initialSources }: { initialSources: Source[] }) {
  const [sources, setSources] = useState(initialSources);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editValues, setEditValues] = useState<FormValues>(EMPTY_FORM);
  const [addValues, setAddValues] = useState<FormValues>(EMPTY_FORM);
  const [showAddForm, setShowAddForm] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const [searchQuery, setSearchQuery] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("all");
  const [adapterFilter, setAdapterFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");
  const [sortKey, setSortKey] = useState<SortKey | null>(null);
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");

  function handleSort(key: SortKey) {
    if (sortKey === key) {
      setSortDir((current) => (current === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("asc");
    }
  }

  function resetFilters() {
    setSearchQuery("");
    setCategoryFilter("all");
    setAdapterFilter("all");
    setStatusFilter("all");
  }

  const hasActiveFilters =
    searchQuery !== "" || categoryFilter !== "all" || adapterFilter !== "all" || statusFilter !== "all";

  const visibleSources = useMemo(() => {
    const query = searchQuery.trim().toLowerCase();
    const filtered = sources.filter((source) => {
      if (categoryFilter !== "all" && source.category !== categoryFilter) return false;
      if (adapterFilter !== "all" && source.adapter !== adapterFilter) return false;
      if (statusFilter !== "all" && getStatus(source) !== statusFilter) return false;
      if (query && !source.name.toLowerCase().includes(query) && !source.url.toLowerCase().includes(query)) {
        return false;
      }
      return true;
    });

    if (!sortKey) return filtered;
    const direction = sortDir === "asc" ? 1 : -1;
    return [...filtered].sort(
      (a, b) => direction * compareSortValues(getSortValue(a, sortKey), getSortValue(b, sortKey)),
    );
  }, [sources, searchQuery, categoryFilter, adapterFilter, statusFilter, sortKey, sortDir]);

  function beginEdit(source: Source) {
    setError(null);
    setEditingId(source.id);
    setEditValues(toFormValues(source));
  }

  async function saveEdit(sourceId: string) {
    setError(null);
    setBusyId(sourceId);
    try {
      const updated = await apiFetchJson<Source>(`/api/v1/sources/${sourceId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(toPayload(editValues)),
      });
      setSources((current) => current.map((s) => (s.id === sourceId ? updated : s)));
      setEditingId(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Update failed");
    } finally {
      setBusyId(null);
    }
  }

  async function toggleEnabled(source: Source) {
    setError(null);
    setBusyId(source.id);
    try {
      const updated = await apiFetchJson<Source>(`/api/v1/sources/${source.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: !source.enabled }),
      });
      setSources((current) => current.map((s) => (s.id === source.id ? updated : s)));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Update failed");
    } finally {
      setBusyId(null);
    }
  }

  async function deleteSource(source: Source) {
    if (!window.confirm(`Delete "${source.name}"? Jobs already discovered will be kept.`)) {
      return;
    }
    setError(null);
    setBusyId(source.id);
    try {
      const response = await apiFetch(`/api/v1/sources/${source.id}?confirm=true`, {
        method: "DELETE",
      });
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new Error(body?.detail ?? `Request failed with ${response.status}`);
      }
      setSources((current) => current.filter((s) => s.id !== source.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Delete failed");
    } finally {
      setBusyId(null);
    }
  }

  async function createSource(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      const created = await apiFetchJson<Source>("/api/v1/sources", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(toPayload(addValues)),
      });
      setSources((current) => [...current, created]);
      setAddValues(EMPTY_FORM);
      setShowAddForm(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Create failed");
    }
  }

  return (
    <>
      {error ? <p className="formError">{error}</p> : null}

      <div className="pageHeader" style={{ marginBottom: "1rem" }}>
        <span />
        <button type="button" onClick={() => setShowAddForm((current) => !current)}>
          {showAddForm ? "Cancel" : "Add source"}
        </button>
      </div>

      {showAddForm ? (
        <form className="panel" onSubmit={createSource} style={{ marginBottom: "1.5rem" }}>
          <SourceFormFields values={addValues} onChange={setAddValues} />
          <button type="submit">Create source</button>
        </form>
      ) : null}

      <div className="tableFilters">
        <input
          type="search"
          placeholder="Search name or URL"
          value={searchQuery}
          onChange={(event) => setSearchQuery(event.target.value)}
        />
        <select value={categoryFilter} onChange={(event) => setCategoryFilter(event.target.value)}>
          <option value="all">All categories</option>
          {CATEGORIES.map((category) => (
            <option key={category} value={category}>
              {category.replaceAll("_", " ")}
            </option>
          ))}
        </select>
        <select value={adapterFilter} onChange={(event) => setAdapterFilter(event.target.value)}>
          <option value="all">All adapters</option>
          {ADAPTERS.map((adapter) => (
            <option key={adapter} value={adapter}>
              {adapter}
            </option>
          ))}
        </select>
        <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
          <option value="all">All statuses</option>
          {(Object.keys(STATUS_LABELS) as SourceStatus[]).map((status) => (
            <option key={status} value={status}>
              {STATUS_LABELS[status]}
            </option>
          ))}
        </select>
        {hasActiveFilters ? (
          <button type="button" className="ghostButton" onClick={resetFilters}>
            Reset filters
          </button>
        ) : null}
        <span className="filterCount">
          {visibleSources.length} of {sources.length} sources
        </span>
      </div>

      <div className="tableWrap">
        <table>
          <thead>
            <tr>
              {SORTABLE_COLUMNS.map(({ key, label }) => (
                <th
                  key={key}
                  aria-sort={sortKey === key ? (sortDir === "asc" ? "ascending" : "descending") : "none"}
                >
                  <button type="button" className="sortHeader" onClick={() => handleSort(key)}>
                    {label}
                    <span className="sortIndicator">
                      {sortKey === key ? (sortDir === "asc" ? "▲" : "▼") : ""}
                    </span>
                  </button>
                </th>
              ))}
              <th aria-label="Actions" />
            </tr>
          </thead>
          <tbody>
            {visibleSources.length === 0 ? (
              <tr>
                <td colSpan={7} className="emptyState">
                  No sources match the current filters.
                </td>
              </tr>
            ) : null}
            {visibleSources.map((source) =>
              editingId === source.id ? (
                <tr key={source.id}>
                  <td colSpan={7}>
                    <SourceFormFields values={editValues} onChange={setEditValues} />
                    <div className="rowActions">
                      <button
                        type="button"
                        disabled={busyId === source.id}
                        onClick={() => saveEdit(source.id)}
                      >
                        Save
                      </button>
                      <button
                        type="button"
                        className="ghostButton"
                        onClick={() => setEditingId(null)}
                      >
                        Cancel
                      </button>
                    </div>
                  </td>
                </tr>
              ) : (
                <tr key={source.id}>
                  <td>
                    <Link href={`/sources/${source.id}`}>{source.name}</Link>
                    <small>
                      <a href={source.url} rel="noreferrer" target="_blank">
                        {source.url}
                      </a>
                    </small>
                  </td>
                  <td>{source.category.replaceAll("_", " ")}</td>
                  <td>
                    <code>{source.adapter}</code>
                  </td>
                  <td>{formatDate(source.last_success_at)}</td>
                  <td>{source.last_job_count ?? "—"}</td>
                  <td>
                    <span className="rowActions">
                      {source.last_error ? (
                        <span className="status bad" title={source.last_error}>
                          Failed
                        </span>
                      ) : source.enabled ? (
                        <span className="status good">Enabled</span>
                      ) : (
                        <span className="status neutral">Disabled</span>
                      )}
                      {source.consecutive_failures >= 2 ? (
                        <span
                          className="status warn"
                          title={`${source.consecutive_failures} failed runs in a row`}
                        >
                          Repeated failures
                        </span>
                      ) : null}
                    </span>
                  </td>
                  <td>
                    <div className="rowActions">
                      {source.enabled ? <CollectButton sourceId={source.id} /> : null}
                      <button
                        type="button"
                        className="ghostButton"
                        disabled={busyId === source.id}
                        onClick={() => beginEdit(source)}
                      >
                        Edit
                      </button>
                      <button
                        type="button"
                        className="ghostButton"
                        disabled={busyId === source.id}
                        onClick={() => toggleEnabled(source)}
                      >
                        {source.enabled ? "Disable" : "Enable"}
                      </button>
                      <button
                        type="button"
                        className="ghostButton dangerButton"
                        disabled={busyId === source.id}
                        onClick={() => deleteSource(source)}
                      >
                        Delete
                      </button>
                    </div>
                  </td>
                </tr>
              ),
            )}
          </tbody>
        </table>
      </div>
    </>
  );
}
