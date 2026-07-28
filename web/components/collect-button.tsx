"use client";

import { useState } from "react";

type Props = {
  sourceId: string;
};

export function CollectButton({ sourceId }: Props) {
  const [state, setState] = useState<"idle" | "working" | "done" | "error">("idle");

  async function queueCollection() {
    setState("working");
    try {
      const base = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
      const response = await fetch(`${base}/api/v1/sources/${sourceId}/collect`, {
        method: "POST",
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      setState("done");
    } catch {
      setState("error");
    }
  }

  const labels = {
    idle: "Collect",
    working: "Queueing…",
    done: "Queued",
    error: "Try again",
  };

  return (
    <button disabled={state === "working" || state === "done"} onClick={queueCollection}>
      {labels[state]}
    </button>
  );
}
