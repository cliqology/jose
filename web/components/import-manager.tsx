"use client";

import { useRef, useState } from "react";
import type { ImportRun } from "@/lib/api";
import { apiFetchJson } from "@/lib/browser-api";

type PreviewRow = {
  row_number: number;
  name: string;
  url: string;
  category: string | null;
  action: string;
  reason: string | null;
};

type Preview = {
  filename: string;
  created: number;
  updated: number;
  skipped: number;
  flagged: number;
  rows: PreviewRow[];
};

function formatDate(value: string): string {
  return new Date(value).toLocaleString();
}

export function ImportManager({ initialRuns }: { initialRuns: ImportRun[] }) {
  const fileInput = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [runs, setRuns] = useState(initialRuns);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function runPreview() {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const formData = new FormData();
      formData.append("file", file);
      const result = await apiFetchJson<Preview>("/api/v1/sources/import/preview", {
        method: "POST",
        body: formData,
      });
      setPreview(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Preview failed");
    } finally {
      setBusy(false);
    }
  }

  async function commitImport() {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const formData = new FormData();
      formData.append("file", file);
      const run = await apiFetchJson<ImportRun>("/api/v1/sources/import/commit", {
        method: "POST",
        body: formData,
      });
      setRuns((current) => [run, ...current]);
      setPreview(null);
      setFile(null);
      if (fileInput.current) fileInput.current.value = "";
    } catch (err) {
      setError(err instanceof Error ? err.message : "Import failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      {error ? <p className="formError">{error}</p> : null}

      <div className="panel" style={{ marginBottom: "1.5rem" }}>
        <input
          ref={fileInput}
          type="file"
          accept=".xlsx"
          onChange={(event) => {
            setFile(event.target.files?.[0] ?? null);
            setPreview(null);
          }}
        />
        <div className="rowActions" style={{ marginTop: "1rem" }}>
          <button type="button" disabled={!file || busy} onClick={runPreview}>
            Preview
          </button>
          <button
            type="button"
            className="ghostButton"
            disabled={!preview || busy}
            onClick={commitImport}
          >
            Confirm import
          </button>
        </div>
      </div>

      {preview ? (
        <div className="panel" style={{ marginBottom: "1.5rem" }}>
          <div className="panelHeader">
            <div>
              <p className="eyebrow">Preview</p>
              <h2>{preview.filename}</h2>
            </div>
            <span className="countPill">
              {preview.created} create · {preview.updated} update · {preview.skipped} skip ·{" "}
              {preview.flagged} flag
            </span>
          </div>
          {preview.rows.length ? (
            <div className="tableWrap">
              <table>
                <thead>
                  <tr>
                    <th>Row</th>
                    <th>Name</th>
                    <th>URL</th>
                    <th>Category</th>
                    <th>Action</th>
                    <th>Reason</th>
                  </tr>
                </thead>
                <tbody>
                  {preview.rows.map((row) => (
                    <tr key={row.row_number}>
                      <td>{row.row_number}</td>
                      <td>{row.name}</td>
                      <td>
                        <small>{row.url}</small>
                      </td>
                      <td>{row.category ?? "—"}</td>
                      <td>
                        <span
                          className={
                            row.action === "flag"
                              ? "status bad"
                              : row.action === "create"
                                ? "status good"
                                : "status neutral"
                          }
                        >
                          {row.action}
                        </span>
                      </td>
                      <td>{row.reason ?? ""}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="emptyState">Nothing to create, update, or flag.</p>
          )}
        </div>
      ) : null}

      <div className="panel">
        <div className="panelHeader">
          <div>
            <p className="eyebrow">Retained reports</p>
            <h2>Past imports</h2>
          </div>
        </div>
        {runs.length ? (
          <div className="tableWrap">
            <table>
              <thead>
                <tr>
                  <th>When</th>
                  <th>File</th>
                  <th>Created</th>
                  <th>Updated</th>
                  <th>Skipped</th>
                  <th>Flagged</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((run) => (
                  <tr key={run.id}>
                    <td>{formatDate(run.completed_at)}</td>
                    <td>{run.filename}</td>
                    <td>{run.created_count}</td>
                    <td>{run.updated_count}</td>
                    <td>{run.skipped_count}</td>
                    <td>{run.flagged_count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="emptyState">No imports have been run yet.</p>
        )}
      </div>
    </>
  );
}
