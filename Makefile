.PHONY: help install-emulator start-emulator stop-emulator setup check bootstrap api worker test demo docker-up docker-down frontend frontend-install frontend-test clean

PY := .venv/bin/python
PORT = $(or $(API_PORT),8000)

help: ## List all targets with descriptions
	@grep -E '^[a-z0-9-]+:.*?## ' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-16s %s\n", $$1, $$2}'

install-emulator: ## Install AWS Emulator (Debian/Ubuntu; skips if present)
	scripts/install_emulator.sh

start-emulator: ## Start the emulator in the background (no-op if healthy)
	scripts/start_emulator.sh

stop-emulator: ## Stop the emulator this project started (PID file only)
	scripts/stop_emulator.sh

setup: ## Create .venv and install dependencies
	python3 -m venv .venv
	.venv/bin/pip install -r requirements-dev.txt

check: ## Verify shell env, emulator health and account 000000000000
	scripts/check_env.sh

bootstrap: ## Create S3 bucket, DynamoDB table, SQS queue (idempotent)
	$(PY) -m app.bootstrap

api: ## Run the FastAPI server (needs emulator env + bootstrap)
	$(PY) -m uvicorn app.main:app --host 127.0.0.1 --port $(PORT)

worker: ## Run the background SQS worker (needs emulator env + bootstrap)
	$(PY) -m app.worker

test: ## Run unit + integration tests (needs emulator env)
	$(PY) -m pytest -v

demo: ## Upload a sample file and poll until PROCESSED (needs api + worker)
	scripts/demo.sh

docker-up: ## Build and start containerized api + worker (Linux, host net)
	UID="$$(id -u)" GID="$$(id -g)" docker compose up --build -d
	docker compose ps

docker-down: ## Stop the containerized api + worker
	docker compose down

frontend-install: ## Install React frontend dependencies
	npm --prefix frontend install

frontend: ## Run the React dev server on http://127.0.0.1:5173
	npm --prefix frontend run dev -- --host 127.0.0.1 --port 5173

frontend-test: ## Run the React component tests
	npm --prefix frontend test

clean: ## Remove venv, caches and run files (never emulator data)
	rm -rf .venv .run __pycache__ app/__pycache__ tests/__pycache__ .pytest_cache
