"use client";

import { useState } from "react";
import { apiFetchJson } from "@/lib/browser-api";

const DECISIONS: { value: string; label: string }[] = [
  { value: "applied", label: "Applied" },
  { value: "irrelevant", label: "Irrelevant" },
  { value: "watch", label: "Watch" },
  { value: "archived", label: "Archived" },
];

export function JobDecisionControls({
  jobId,
  decision,
  onChange,
}: {
  jobId: string;
  decision: string | null;
  onChange: (decision: string | null) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function setDecision(next: string | null) {
    setError(null);
    setBusy(true);
    try {
      const updated = await apiFetchJson<{ id: string; user_decision: string | null }>(
        `/api/v1/jobs/${jobId}/decision`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ decision: next }),
        },
      );
      onChange(updated.user_decision);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Update failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rowActions">
      {DECISIONS.map(({ value, label }) => (
        <button
          key={value}
          type="button"
          className={decision === value ? "" : "ghostButton"}
          disabled={busy}
          onClick={() => setDecision(decision === value ? null : value)}
        >
          {label}
        </button>
      ))}
      {error ? <span className="formError">{error}</span> : null}
    </div>
  );
}
