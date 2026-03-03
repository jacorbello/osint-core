.DEFAULT_GOAL := help

IMAGE := harbor.corbello.io/osint/osint-core
SHA   := $(shell git rev-parse --short HEAD 2>/dev/null || echo "dev")

.PHONY: help format lint typecheck test check check-full build push scan dev dev-down dev-down-clean logs precommit clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-18s\033[0m %s\n", $$1, $$2}'

format: ## Auto-fix lint issues and format code
	ruff check --fix src/ tests/
	ruff format src/ tests/

lint: ## Run ruff linter
	ruff check src/ tests/

typecheck: ## Run mypy strict type checking
	mypy src/osint_core/

test: ## Run pytest with coverage
	pytest --cov=osint_core --cov-report=term-missing -v

check: lint typecheck test ## Run all checks (read-only, mirrors CI)

check-full: check scan ## Run all checks including container scan

build: ## Build Docker image tagged with git SHA
	docker build --target api -t $(IMAGE):$(SHA) -t $(IMAGE):local .

push: ## Push SHA-tagged image to Harbor
	docker push $(IMAGE):$(SHA)

scan: ## Trivy scan (mirrors CI flags)
	trivy image --severity HIGH,CRITICAL --ignore-unfixed --exit-code 1 --ignorefile .trivyignore $(IMAGE):local

dev: ## Start local dev stack
	docker compose -f docker-compose.dev.yaml up --build

dev-down: ## Stop local dev stack
	docker compose -f docker-compose.dev.yaml down

dev-down-clean: ## Stop local dev stack and remove volumes
	docker compose -f docker-compose.dev.yaml down -v

logs: ## Tail local dev stack logs
	docker compose -f docker-compose.dev.yaml logs -f

precommit: format check ## Format and run all checks

clean: ## Remove Python cache artifacts
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
