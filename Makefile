.PHONY: setup up down logs test backend-test frontend-check migrations

setup:
	cp -n .env.example .env || true

up:
	docker compose up --build -d

down:
	docker compose down

logs:
	docker compose logs -f --tail=100

test: backend-test frontend-check

backend-test:
	cd backend && pytest

frontend-check:
	cd frontend && npm run lint && npm run build

migrations:
	docker compose run --rm backend python manage.py makemigrations

