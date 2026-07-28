SHELL := /bin/bash

.PHONY: doctor setup dev down logs test lint build migrate import-sources collect collect-all seed shell-api shell-db reset-db

doctor:
	./scripts/doctor.sh

setup:
	./scripts/bootstrap.sh

dev:
	@test -f .env || cp .env.example .env
	docker compose up --build

down:
	docker compose down

logs:
	docker compose logs -f --tail=200

test:
	docker compose run --rm api sh -c "alembic upgrade head && pytest"

lint:
	docker compose run --rm api ruff check jose tests
	docker compose run --rm web npm run lint

build:
	docker compose build
	docker compose run --rm -v /app/.next web npm run build

migrate:
	docker compose run --rm api alembic upgrade head

seed:
	docker compose run --rm api python -m jose.cli seed

import-sources:
	docker compose run --rm api python -m jose.cli import-sources /data/import/VC_Job_Search_Resources.xlsx

collect-all:
	docker compose run --rm api python -m jose.cli enqueue-collect-all

collect:
	@test -n "$(SOURCE_ID)" || (echo "Usage: make collect SOURCE_ID=<uuid>" && exit 1)
	docker compose run --rm api python -m jose.cli collect-source $(SOURCE_ID)

shell-api:
	docker compose exec api bash

shell-db:
	docker compose exec db psql -U $${POSTGRES_USER:-jose} -d $${POSTGRES_DB:-jose}

reset-db:
	docker compose down -v
	docker compose up -d db
	docker compose run --rm api alembic upgrade head
