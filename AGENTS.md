# AGENTS.md — Codex Review and Implementation Guide

Read `docs/PRD.md`, `CLAUDE.md`, and the relevant backlog issue before editing.

## Codex's preferred role

Codex should act as a skeptical second engineer:

- Review Claude Code changes
- Find missing tests and edge cases
- Verify migrations
- Check retry and idempotency behavior
- Check user-data isolation
- Check that failures are not swallowed
- Check that no AI-generated claim can escape without evidence
- Check that external actions retain approval gates

## Review checklist

- Does every new persisted record include `user_id` where applicable?
- Can the task be retried without duplicating jobs or source links?
- Is the collector deterministic for the same payload?
- Are external URLs validated and timeouts bounded?
- Are errors visible in `source_runs` or `tasks`?
- Are credentials absent from logs and commits?
- Is the route thin and the service testable?
- Is there a migration and downgrade path?
- Is the cloud path unchanged from local behavior?

Use `make test` and `make lint`. Report concrete findings before broad stylistic preferences.
