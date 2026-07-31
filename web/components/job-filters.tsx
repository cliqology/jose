"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useState, type FormEvent } from "react";

const ATS_TYPES = ["ashby", "greenhouse", "lever", "jsonld", "generic"];
const STATUSES = ["active", "removed"];
const DECISIONS = ["applied", "irrelevant", "watch", "archived"];

type SourceOption = { id: string; name: string };

export function JobFilters({ sources }: { sources: SourceOption[] }) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const [company, setCompany] = useState(searchParams.get("company") ?? "");
  const [title, setTitle] = useState(searchParams.get("title") ?? "");
  const [location, setLocation] = useState(searchParams.get("location") ?? "");
  const [dateFrom, setDateFrom] = useState(searchParams.get("date_from") ?? "");
  const [dateTo, setDateTo] = useState(searchParams.get("date_to") ?? "");
  const [sourceId, setSourceId] = useState(searchParams.get("source_id") ?? "");
  const [atsType, setAtsType] = useState(searchParams.get("ats_type") ?? "");
  const [status, setStatus] = useState(searchParams.get("status") ?? "");
  const [decision, setDecision] = useState(searchParams.get("decision") ?? "");

  function applyFilters(event: FormEvent) {
    event.preventDefault();
    const params = new URLSearchParams();
    if (company) params.set("company", company);
    if (title) params.set("title", title);
    if (location) params.set("location", location);
    if (dateFrom) params.set("date_from", dateFrom);
    if (dateTo) params.set("date_to", dateTo);
    if (sourceId) params.set("source_id", sourceId);
    if (atsType) params.set("ats_type", atsType);
    if (status) params.set("status", status);
    if (decision) params.set("decision", decision);
    router.push(params.toString() ? `${pathname}?${params.toString()}` : pathname);
  }

  function resetFilters() {
    setCompany("");
    setTitle("");
    setLocation("");
    setDateFrom("");
    setDateTo("");
    setSourceId("");
    setAtsType("");
    setStatus("");
    setDecision("");
    router.push(pathname);
  }

  const hasActiveFilters = Boolean(
    company || title || location || dateFrom || dateTo || sourceId || atsType || status || decision,
  );

  return (
    <form className="tableFilters" onSubmit={applyFilters}>
      <input
        type="search"
        placeholder="Company"
        value={company}
        onChange={(event) => setCompany(event.target.value)}
      />
      <input
        type="search"
        placeholder="Title"
        value={title}
        onChange={(event) => setTitle(event.target.value)}
      />
      <input
        type="search"
        placeholder="Location"
        value={location}
        onChange={(event) => setLocation(event.target.value)}
      />
      <select value={sourceId} onChange={(event) => setSourceId(event.target.value)}>
        <option value="">All sources</option>
        {sources.map((source) => (
          <option key={source.id} value={source.id}>
            {source.name}
          </option>
        ))}
      </select>
      <select value={atsType} onChange={(event) => setAtsType(event.target.value)}>
        <option value="">All ATS types</option>
        {ATS_TYPES.map((type) => (
          <option key={type} value={type}>
            {type}
          </option>
        ))}
      </select>
      <select value={status} onChange={(event) => setStatus(event.target.value)}>
        <option value="">All statuses</option>
        {STATUSES.map((value) => (
          <option key={value} value={value}>
            {value}
          </option>
        ))}
      </select>
      <select value={decision} onChange={(event) => setDecision(event.target.value)}>
        <option value="">Needs review (default)</option>
        {DECISIONS.map((value) => (
          <option key={value} value={value}>
            {value}
          </option>
        ))}
      </select>
      <input
        type="date"
        aria-label="From date"
        value={dateFrom}
        onChange={(event) => setDateFrom(event.target.value)}
      />
      <input
        type="date"
        aria-label="To date"
        value={dateTo}
        onChange={(event) => setDateTo(event.target.value)}
      />
      <button type="submit">Apply filters</button>
      {hasActiveFilters ? (
        <button type="button" className="ghostButton" onClick={resetFilters}>
          Reset filters
        </button>
      ) : null}
    </form>
  );
}
