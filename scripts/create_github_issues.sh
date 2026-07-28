#!/usr/bin/env bash
set -euo pipefail

if ! command -v gh >/dev/null 2>&1; then
  echo "GitHub CLI (gh) is required for this optional script."
  exit 1
fi

cat <<'LIST'
Create GitHub issues from docs/backlog/PHASE_0_1_BACKLOG.md one at a time.
The backlog is deliberately written for human review before issue creation.
Recommended labels: phase-0, phase-1, backend, frontend, infrastructure, security, collector.
LIST
