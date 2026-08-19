.PHONY: help install dev lint format typecheck test test-unit test-integration test-api \
        migrate migrate-create db-reset run mcp-server docker-up docker-down clean

PROJECT_DIR := ai-github-architect
PYTHON := python3
UV := uv

help: ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-25s\033[0m %s\n", $$1, $$2}'

# ─── Installation ────────────────────────────────────────────────────────────

install: ## Install all dependencies (requires uv)
	$(UV) sync --all-extras

install-dev: ## Install with dev dependencies
	$(UV) sync --all-extras --dev

# ─── Code Quality ────────────────────────────────────────────────────────────

lint: ## Run ruff linter
	$(UV) run ruff check app/ tests/

format: ## Auto-format with ruff
	$(UV) run ruff format app/ tests/
	$(UV) run ruff check --fix app/ tests/

typecheck: ## Run mypy type checker
	$(UV) run mypy app/

# ─── Testing ─────────────────────────────────────────────────────────────────

test: ## Run all tests
	$(UV) run pytest tests/ -v --cov=app --cov-report=term-missing

test-unit: ## Run unit tests only
	$(UV) run pytest tests/unit/ -v

test-integration: ## Run integration tests only
	$(UV) run pytest tests/integration/ -v

test-api: ## Run API tests only
	$(UV) run pytest tests/api/ -v

test-fast: ## Run tests without coverage (faster)
	$(UV) run pytest tests/ -v -x

# ─── Database ─────────────────────────────────────────────────────────────────

migrate: ## Run all pending migrations
	$(UV) run alembic upgrade head

migrate-create: ## Create a new migration (usage: make migrate-create MSG="your message")
	$(UV) run alembic revision --autogenerate -m "$(MSG)"

migrate-down: ## Rollback last migration
	$(UV) run alembic downgrade -1

db-reset: ## Drop and recreate the database schema (DESTRUCTIVE)
	@read -p "Are you sure? This will drop all data. [y/N] " confirm && \
	[ "$$confirm" = "y" ] && $(UV) run alembic downgrade base && $(UV) run alembic upgrade head

# ─── Running ─────────────────────────────────────────────────────────────────

run: ## Run FastAPI development server
	$(UV) run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

mcp-server: ## Run the GitHub MCP server standalone
	$(UV) run python -m app.mcp.github_server.server

# ─── Docker ──────────────────────────────────────────────────────────────────

docker-up: ## Start all services with Docker Compose
	docker compose up -d

docker-up-build: ## Build and start all services
	docker compose up -d --build

docker-down: ## Stop all services
	docker compose down

docker-logs: ## Follow logs for all services
	docker compose logs -f

docker-clean: ## Stop services and remove volumes (DESTRUCTIVE)
	docker compose down -v

# ─── Cleanup ─────────────────────────────────────────────────────────────────

clean: ## Remove build artifacts and caches
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage dist build *.egg-info
