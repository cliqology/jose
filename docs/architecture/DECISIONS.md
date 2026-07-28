# Architecture Decisions

## ADR-001: PostgreSQL from the first migration

**Decision:** Use PostgreSQL locally and in the cloud.

**Reason:** Avoid a SQLite-to-PostgreSQL behavioral migration and establish multi-user-safe data ownership from the beginning.

## ADR-002: Database-backed task queue for MVP

**Decision:** Use PostgreSQL rows and `FOR UPDATE SKIP LOCKED` for background work.

**Reason:** It is inexpensive, understandable, and adequate for one user and modest source volume.

## ADR-003: Separate web, API, and worker processes

**Decision:** Long-running work does not execute inside web requests.

**Reason:** The same design works on a laptop and on cloud container hosts, and it allows independent scaling later.

## ADR-004: Provider-neutral AI boundary

**Decision:** AI scoring and writing features will call internal service interfaces rather than provider SDKs directly from business logic.

**Reason:** Model cost, quality, and provider availability will change.

## ADR-005: Human approval for consequential actions

**Decision:** Final applications and outgoing messages always require user approval.

**Reason:** JOSE assists judgment; it does not impersonate the user or create reputational risk through autonomous outreach.

## ADR-006: No n8n dependency for MVP

**Decision:** Scheduling and orchestration use application code, a worker, and a cloud scheduler.

**Reason:** This minimizes cost and keeps the core behavior testable in one repository. n8n may be introduced later if integration complexity justifies it.
