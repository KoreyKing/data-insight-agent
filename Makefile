.PHONY: check backend-check frontend-check backend-dev frontend-dev dev smoke-local smoke status

check: backend-check frontend-check

backend-check:
	cd backend && uv run ruff check . && uv run pytest

frontend-check:
	cd frontend && pnpm typecheck && pnpm lint && pnpm build

backend-dev:
	cd backend && uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

frontend-dev:
	cd frontend && pnpm dev --host 127.0.0.1 --port 5173

dev:
	$(MAKE) -j2 backend-dev frontend-dev

smoke-local:
	curl -fsS http://127.0.0.1:8000/health
	curl -fsS http://127.0.0.1:5173 >/dev/null

smoke:
	docker compose -f docker-compose.yml -f docker-compose.dev.yml config --quiet
	docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
	for attempt in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do curl -fsS http://localhost:8000/health >/dev/null 2>&1 && break; sleep 1; test "$$attempt" -lt 20; done
	curl -fsS http://localhost:8000/health
	for attempt in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do curl -fsS http://localhost:8000/ >/dev/null 2>&1 && break; sleep 1; test "$$attempt" -lt 20; done
	curl -fsS http://localhost:8000/ >/dev/null

status:
	git branch --show-current
	git status --short --branch
	docker compose ps
