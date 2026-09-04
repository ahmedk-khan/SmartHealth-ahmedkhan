.PHONY: up down test infra-test seed seed-users lint migrate demo prod-env prod-up prod-down prod-migrate

up:
	docker compose up --build

down:
	docker compose down

demo:
	docker compose up --build

prod-env:
	@echo "Create a production env file from .env.production.example if needed:"
	@echo "copy .env.production.example .env.production"

prod-up:
	@echo "Starting production stack using .env.production"
	@docker compose --env-file .env.production up -d --build

prod-down:
	@echo "Stopping production stack"
	@docker compose --env-file .env.production down

prod-migrate:
	@echo "Running production migrations"
	@docker compose --env-file .env.production run --rm migrate

test:
	python -m pytest -q

infra-test:
	RUN_DOCKER_INTEGRATION=1 python -m pytest -q tests/integration -m integration

seed:
	python -m scripts.seed

seed-users:
	python -m scripts.seed_users

migrate:
	alembic upgrade head

lint:
	ruff check app tests scripts
