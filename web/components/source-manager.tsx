"use client";

import { useState } from "react";
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

export function SourceManager({ initialSources }: { initialSources: Source[] }) {
  const [sources, setSources] = useState(initialSources);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editValues, setEditValues] = useState<FormValues>(EMPTY_FORM);
  const [addValues, setAddValues] = useState<FormValues>(EMPTY_FORM);
  const [showAddForm, setShowAddForm] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

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

      <div className="tableWrap">
        <table>
          <thead>
            <tr>
              <th>Source</th>
              <th>Category</th>
              <th>Adapter</th>
              <th>Last success</th>
              <th>Jobs</th>
              <th>Status</th>
              <th aria-label="Actions" />
            </tr>
          </thead>
          <tbody>
            {sources.map((source) =>
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
                    <a href={source.url} rel="noreferrer" target="_blank">
                      {source.name}
                    </a>
                    <small>{source.url}</small>
                  </td>
                  <td>{source.category.replaceAll("_", " ")}</td>
                  <td>
                    <code>{source.adapter}</code>
                  </td>
                  <td>{formatDate(source.last_success_at)}</td>
                  <td>{source.last_job_count ?? "—"}</td>
                  <td>
                    {source.last_error ? (
                      <span className="status bad" title={source.last_error}>
                        Failed
                      </span>
                    ) : source.enabled ? (
                      <span className="status good">Enabled</span>
                    ) : (
                      <span className="status neutral">Disabled</span>
                    )}
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
