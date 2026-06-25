# Titan Omega — one-command developer workflow.
# Non-technical owners: see START_HERE.md.

.PHONY: help install install-backend install-frontend dev backend frontend test build

help:
	@echo "Titan Omega"
	@echo "  make install   Install backend + frontend dependencies (run once)"
	@echo "  make dev       Run the core (:8000) and dashboard (:3000) together"
	@echo "  make backend   Run only the Executive Intelligence Core (:8000)"
	@echo "  make frontend  Run only the Empire Command Center (:3000)"
	@echo "  make test      Run the backend test suite"
	@echo "  make build     Production build of the dashboard"

install: install-backend install-frontend

install-backend:
	cd backend && pip install -r requirements.txt

install-frontend:
	cd frontend && npm install

# Run both. The backend runs in the background; Ctrl+C stops the frontend, then
# the trap stops the backend.
dev:
	@echo "Starting Executive Intelligence Core on :8000 ..."
	@cd backend && uvicorn app.main:app --port 8000 & echo $$! > /tmp/titan-backend.pid
	@echo "Starting Empire Command Center on :3000 ..."
	@trap 'kill `cat /tmp/titan-backend.pid` 2>/dev/null' EXIT; cd frontend && npm run dev

backend:
	cd backend && uvicorn app.main:app --reload --port 8000

frontend:
	cd frontend && npm run dev

test:
	cd backend && python -m pytest -q

build:
	cd frontend && npm run build
