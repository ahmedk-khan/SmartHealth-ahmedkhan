.PHONY: up down test seed lint migrate demo

up:
	docker compose up --build

down:
	docker compose down

demo:
	docker compose up --build

test:
	python -m pytest -q

seed:
	python -m scripts.seed

migrate:
	alembic upgrade head

lint:
	ruff check app tests scripts
