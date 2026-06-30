.PHONY: up down logs test clean migrate inspect-dlq seed verify-slos portfolio-verify load-verify observability-up observability-down observability-verify

up:
	docker compose up -d --build

down:
	docker compose down -v

logs:
	docker compose logs -f

test:
	python -m pytest tests/ -v

migrate:
	docker exec reliability-lab-postgres-1 psql -U reliability -d reliability_lab \
		-c "ALTER TABLE messages ADD COLUMN IF NOT EXISTS index_status VARCHAR(30) NOT NULL DEFAULT 'pending';" \
		-c "ALTER TABLE messages ADD COLUMN IF NOT EXISTS index_error TEXT;"

clean:
	docker compose down -v
	rm -rf .pytest_cache __pycache__

inspect-dlq:
	docker compose exec worker python scripts/inspect_dlq.py $(ARGS)

seed:
	python scripts/seed_messages.py $(ARGS)

verify-slos:
	python scripts/verify_slos.py $(ARGS)

portfolio-verify:
	python scripts/portfolio_verify.py $(ARGS)

load-verify:
	python scripts/load_verify.py $(ARGS)

observability-up:
	docker compose -f docker-compose.observability.yml up -d

observability-down:
	docker compose -f docker-compose.observability.yml down

observability-verify:
	python scripts/observability_verify.py
