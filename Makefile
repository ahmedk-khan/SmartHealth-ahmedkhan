.PHONY: up down test infra-test seed lint migrate demo

up:
	docker compose up --build

down:
	docker compose down

demo:
	docker compose up --build

test:
	python -m pytest -q

infra-test:
	RUN_DOCKER_INTEGRATION=1 python -m pytest -q tests/integration -m integration

seed:
	python -m scripts.seed

migrate:
	alembic upgrade head

lint:
	ruff check app tests scripts
