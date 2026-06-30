.PHONY: up down logs test clean migrate inspect-dlq seed verify-slos

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
