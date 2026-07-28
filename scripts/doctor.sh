#!/usr/bin/env bash
set -euo pipefail

fail=0
for command in docker git; do
  if command -v "$command" >/dev/null 2>&1; then
    printf "✓ %s found\n" "$command"
  else
    printf "✗ %s is missing\n" "$command"
    fail=1
  fi
done

if command -v docker >/dev/null 2>&1; then
  if docker info >/dev/null 2>&1; then
    printf "✓ Docker daemon is running\n"
  else
    printf "✗ Docker is installed but not running. Start Docker Desktop.\n"
    fail=1
  fi
fi

if [[ -f docs/PRD.md ]]; then
  printf "✓ docs/PRD.md found\n"
else
  printf "! docs/PRD.md is missing. Move the downloaded PRD there before using Claude Code.\n"
fi

if [[ -f .env ]]; then
  printf "✓ .env found\n"
else
  printf "! .env is missing; make setup will create it from .env.example\n"
fi

if [[ "$fail" -ne 0 ]]; then
  exit 1
fi

printf "JOSE prerequisites look good.\n"
