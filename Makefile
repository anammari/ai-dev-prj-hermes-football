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

.PHONY: help setup build up down db-port migrate models model-ready test itest itest-isolated lint check-notes index-notes search ingest score-delay \
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
	$(TOOLS) build

up: ## Start the stack, apply migrations, serve the API
	$(COMPOSE) up -d db ollama
	@$(MAKE) --no-print-directory model-ready
	@$(MAKE) --no-print-directory migrate
	$(COMPOSE) up -d backend mcp-server hermes ingest
	@sleep 5
	@if [ -z "$$($(COMPOSE) ps --status running --services ingest)" ]; then \
	  echo "ingest scheduler exited at startup (usually a missing UPSTREAM_API_KEY):"; \
	  $(COMPOSE) logs --tail=10 ingest; exit 1; fi
	@if [ -z "$$($(COMPOSE) ps --status running --services backend)" ]; then \
	  echo "backend exited at startup (usually a missing API_AGENT_TOKEN):"; \
	  $(COMPOSE) logs --tail=10 backend; exit 1; fi
	@if [ -z "$$($(COMPOSE) ps --status running --services hermes)" ]; then \
	  echo "hermes gateway exited at startup (check AGENT_TURN_DSN, MCP_SERVER_TOKEN and ROUTER_*):"; \
	  $(COMPOSE) logs --tail=20 hermes; exit 1; fi
	@echo "stack up: db, ollama, backend on http://localhost:$${BACKEND_PORT:-8000} (docs at /docs), mcp-server, hermes gateway, ingest scheduler."
	@echo "gateway health: docker compose exec -T hermes python -c \"import urllib.request as u; print(u.urlopen('http://127.0.0.1:8200/health').read().decode())\""

down: ## Stop everything, keep the volumes
	$(COMPOSE) --profile tools down

db-port: ## Also publish the db on the host port, for development only
	$(COMPOSE) -f docker-compose.yml -f docker-compose.dev.yml up -d db
	@echo "db published on host port $${POSTGRES_PORT:-5432}: the host DATABASE_URL works while this is up"

migrate: ## Apply the Alembic migrations to the Compose database
	$(TOOLS) run --rm migrate

models: ## Pull the pinned embedding model into the ollama volume
	$(TOOLS) run --rm models

# A fresh ollama volume holds no model, so knowledge indexing would fail and every daily run would end
# `partial` until someone ran `make models` by hand. `make up` calls this first. It is a no-op once the
# volume has a model, so it costs nothing on the runs after the first.
model-ready: ## Pull the embedding model if the ollama volume has none yet
	@if $(COMPOSE) exec -T ollama ollama list | tail -n +2 | grep -q .; then \
	  echo "ollama volume already holds a model"; \
	else \
	  echo "no model in the ollama volume: pulling the embedding model (first run only)"; \
	  $(MAKE) --no-print-directory models; \
	fi

test: ## Unit tests: fast, no network, no stack
	$(TOOLS) run --rm tests pytest -q -m "not integration"

itest: ## Integration tests against the running stack (Postgres + pgvector + Ollama)
	$(TOOLS) run --rm -e BACKEND_BASE_URL=http://backend:8000 tests pytest -q -m integration

# Own Compose project, own volumes, throwaway passwords: never touches the retained stack's data.
# The backend gets its own host port so an isolated run can never fight the retained stack's for 8000.
ISOLATED := COMPOSE_PROJECT_NAME=hermes-football-itest POSTGRES_PASSWORD=itest-only AGENT_DB_PASSWORD=itest-only-agent BACKEND_PORT=8010

itest-isolated: ## Integration tests against a throwaway Postgres + Ollama (own project, volumes removed after)
	@set -e; trap '$(ISOLATED) docker compose --profile tools down -v' EXIT; \
	  $(ISOLATED) docker compose up -d db ollama; \
	  $(ISOLATED) docker compose --profile tools run --rm models; \
	  $(ISOLATED) docker compose --profile tools run --rm migrate; \
	  $(ISOLATED) docker compose up -d backend mcp-server; \
	  $(ISOLATED) docker compose --profile tools run --rm \
	    -e BACKEND_BASE_URL=http://backend:8000 \
	    tests pytest -q -m integration

lint: ## Ruff over the repository
	$(TOOLS) run --rm tests ruff check .

check-notes: ## Validate the notes corpus against hermes/agent-knowledge/manifest.yaml
	$(TOOLS) run --rm tests python -m ingest.knowledge check

index-notes: ## Index changed notes into knowledge_chunks
	$(TOOLS) run --rm tests python -m ingest.knowledge index

search: ## Ask the corpus a question: make search Q="how does the playoff work"
	$(TOOLS) run --rm tests python -m ingest.knowledge search "$(Q)"

ingest: ## Trigger one manual upstream collection run
	$(COMPOSE) run --rm ingest python -m ingest run

ask: ## Ask the agent one question through the real pipeline: make ask Q="where are Arsenal?"
	$(TOOLS) run --rm -e BACKEND_BASE_URL=http://backend:8000 tests python -m agent.gateway.ask --message "$(Q)"

score-delay: ## Poll a live or recent match and report how old the provider's data is
	$(COMPOSE) run --rm ingest python -m ingest measure-score-delay $(if $(MATCH_ID),--match-id $(MATCH_ID),)

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
