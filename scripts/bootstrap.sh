#!/usr/bin/env bash
set -euo pipefail

if [[ ! -f .env ]]; then
  cp .env.example .env
  printf "Created .env from .env.example\n"
fi

./scripts/doctor.sh
docker compose build
printf "\nJOSE images are built. Run 'make dev' next.\n"
