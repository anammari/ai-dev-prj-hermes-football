# Hermes Football - developer entry points.
# Everything runs in containers: nothing but Docker, this repository and a `.env` is installed on the
# host (_docs/product-spec.md §4). `make help` lists the targets.

SHELL := /bin/bash
COMPOSE := docker compose
TOOLS := docker compose --profile tools
SPEC  := openapi.yaml
SWAGGER_PORT ?= 8081
SWAGGER_NAME ?= hermes-football-swagger
Q ?=

.PHONY: help setup build up down db-port migrate models test itest lint check-notes index-notes search \
        logs swagger swagger-stop validate-spec

help: ## Show available targets
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  %-16s %s\n", $$1, $$2}'

setup: ## Create .env from .env.example and build the app image
	@test -f .env || { cp .env.example .env; echo "created .env - set POSTGRES_PASSWORD in it before make up"; }
	@$(MAKE) --no-print-directory build

# The tools below run the last built image, so re-run this after changing db/, ingest/ or tests/.
# If buildx cannot write its state directory (a locked-down or sandboxed machine), prefix
# DOCKER_BUILDKIT=0.
build: ## Build the app image used by the migrate and tests services
	$(COMPOSE) build

up: ## Start the stack and apply migrations
	$(COMPOSE) up -d db ollama
	@$(MAKE) --no-print-directory migrate
	@echo "stack up: db, ollama. backend, mcp-server, ingest, hermes, frontend and obs arrive with their own milestones."

down: ## Stop everything, keep the volumes
	$(COMPOSE) --profile tools down

db-port: ## Also publish the db on the host port, for development only
	$(COMPOSE) -f docker-compose.yml -f docker-compose.dev.yml up -d db
	@echo "db published on host port $${POSTGRES_PORT:-5432}: the host DATABASE_URL works while this is up"

migrate: ## Apply the Alembic migrations to the Compose database
	$(TOOLS) run --rm migrate

models: ## Pull the pinned embedding model into the ollama volume
	$(TOOLS) run --rm models

test: ## Unit tests: fast, no network, no stack
	$(TOOLS) run --rm tests pytest -q -m "not integration"

itest: ## Integration tests against the running stack (Postgres + pgvector + Ollama)
	$(TOOLS) run --rm tests pytest -q -m integration

lint: ## Ruff over the repository
	$(TOOLS) run --rm tests ruff check .

check-notes: ## Validate the notes corpus against hermes/agent-knowledge/manifest.yaml
	$(TOOLS) run --rm tests python -m ingest.knowledge check

index-notes: ## Index changed notes into knowledge_chunks
	$(TOOLS) run --rm tests python -m ingest.knowledge index

search: ## Ask the corpus a question: make search Q="how does the playoff work"
	$(TOOLS) run --rm tests python -m ingest.knowledge search "$(Q)"

logs: ## Tail logs: make logs S=db
	$(COMPOSE) logs -f --tail=100 $(S)

swagger: ## Serve the API contract in Swagger UI at http://localhost:$(SWAGGER_PORT)
	@docker rm -f $(SWAGGER_NAME) >/dev/null 2>&1 || true
	docker run --rm -d --name $(SWAGGER_NAME) -p $(SWAGGER_PORT):8080 \
	  -e SWAGGER_JSON=/$(SPEC) \
	  -v "$(CURDIR)/$(SPEC):/usr/share/nginx/html/$(SPEC):ro" \
	  swaggerapi/swagger-ui
	@echo "Swagger UI: http://localhost:$(SWAGGER_PORT)"

swagger-stop: ## Stop the Swagger UI container
	-docker rm -f $(SWAGGER_NAME)

validate-spec: ## Lint the OpenAPI contract
	npx --yes @redocly/cli@latest lint $(SPEC)
