.PHONY: setup test api-dev web-dev web-build docker-up docker-down

setup:
	uv sync --extra dev
	cd apps/web && npm ci

test:
	pytest -q

api-dev:
	uv run uvicorn apps.api.main:app --host 127.0.0.1 --port 8000 --reload

web-dev:
	cd apps/web && npm run dev

web-build:
	cd apps/web && npm run build

docker-up:
	docker compose up --build

docker-down:
	docker compose down
