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
EVAL_ARGS ?=

.PHONY: help setup build up down db-port migrate models model-ready test itest itest-isolated lint check-notes index-notes search ingest score-delay \
        eval eval-self-check eval-backfill frontend-test frontend-types e2e logs swagger swagger-stop validate-spec \
        ci ci-full security-scan scan-secrets scan-deps scan-images lint-workflows \
        obs-up obs-down obs-logs telemetry-smoke oncall-report alert-check alert-fire alert-drill alert-state

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
	$(COMPOSE) up -d backend frontend mcp-server hermes ingest
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
	@if [ -z "$$($(COMPOSE) ps --status running --services frontend)" ]; then \
	  echo "frontend exited at startup (check API_AGENT_TOKEN and the build log):"; \
	  $(COMPOSE) logs --tail=20 frontend; exit 1; fi
	@echo "stack up: db, ollama, backend on http://localhost:$${BACKEND_PORT:-8000} (docs at /docs),"
	@echo "dashboard on http://localhost:$${FRONTEND_PORT:-3000}, mcp-server, hermes gateway, ingest scheduler."
	@echo "gateway health: docker compose exec -T hermes python -c \"import urllib.request as u; print(u.urlopen('http://127.0.0.1:8200/health').read().decode())\""

down: ## Stop everything, keep the volumes
	$(COMPOSE) --profile tools --profile review down

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

review-up: ## Start the public review bot (separate token, allow-all, throttled)
	$(COMPOSE) --profile review up -d hermes-review

review-down: ## Stop the public review bot
	$(COMPOSE) --profile review stop hermes-review

ask: ## Ask the agent one question through the real pipeline: make ask Q="where are Arsenal?"
	$(TOOLS) run --rm -e BACKEND_BASE_URL=http://backend:8000 tests python -m agent.gateway.ask --message "$(Q)"

score-delay: ## Poll a live or recent match and report how old the provider's data is
	$(COMPOSE) run --rm ingest python -m ingest measure-score-delay $(if $(MATCH_ID),--match-id $(MATCH_ID),)

eval: ## Run the golden-question eval (EVAL_ARGS="--limit 4" is a smoke run: metrics only, not stored)
	$(TOOLS) run --rm tests python -m evals.golden.runner $(EVAL_ARGS)

eval-self-check: ## Prove the eval gate can fail (no model, no database)
	$(TOOLS) run --rm tests python -m evals.golden.runner --self-check

eval-backfill: ## Import the two M4 routing artifacts as the scoreboard baseline
	$(TOOLS) run --rm tests python -m evals.golden.backfill

logs: ## Tail logs: make logs S=db
	$(COMPOSE) logs -f --tail=100 $(S)

frontend-types: ## Regenerate the dashboard's API types from openapi.yaml (run after a contract change)
	cd frontend && pnpm gen:api

frontend-test: ## Dashboard lint, typecheck and Vitest, in the pinned browser tool image
	$(COMPOSE) --profile tools run --rm frontend-e2e pnpm lint
	$(COMPOSE) --profile tools run --rm frontend-e2e pnpm typecheck
	$(COMPOSE) --profile tools run --rm frontend-e2e pnpm test

e2e: ## Playwright against the running dashboard (needs `make up`)
	$(COMPOSE) --profile tools run --rm frontend-e2e

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

# --- CI parity and security scans ---------------------------------------------------------------
# `make ci` is what a pull request runs minus the Postgres/Ollama integration job, which needs the
# stack. `make ci-full` is the pre-merge gate the owner runs locally. Neither runs `make eval`: the
# eval sends the golden questions to clef:cloud and is a deliberate, manual owner decision.

ci: ## Local parity with the pull-request CI gates (no stack, no cloud)
	@$(MAKE) --no-print-directory lint test frontend-test eval-self-check security-scan lint-workflows

ci-full: ## Every gate except the eval: unit, lint, integration, dashboard, browser, scans
	@$(MAKE) --no-print-directory ci itest e2e

security-scan: scan-secrets scan-deps ## Secret scan and dependency audit; reports under security/scans/latest

scan-secrets: ## gitleaks over the working tree (never prints a secret; report is redacted)
	@mkdir -p security/scans/latest
	@docker run --rm -u "$$(id -u):$$(id -g)" -e HOME=/tmp -v "$(CURDIR):/repo" -w /repo \
	  ghcr.io/gitleaks/gitleaks:v8.24.0 detect --source=/repo --no-git --redact \
	  --config=/repo/.gitleaks.toml --report-format=json \
	  --report-path=/repo/security/scans/latest/gitleaks.json
	@echo "gitleaks: no leak found"

scan-deps: ## pip-audit and pnpm audit (network: advisories only, no project data)
	@mkdir -p security/scans/latest
	@$(TOOLS) run --rm tests pip-audit --progress-spinner off
	@$(COMPOSE) --profile tools run --rm frontend-e2e pnpm audit --prod --audit-level high

scan-images: ## trivy over the built images (slow; main and nightly, not every push)
	@for image in hermes-football-backend:latest hermes-football-frontend:latest hermes-football-ollama:local; do \
	  echo "scanning $$image"; \
	  docker run --rm -v /var/run/docker.sock:/var/run/docker.sock aquasec/trivy:0.58.1 image \
	    --severity HIGH,CRITICAL --exit-code 1 "$$image" || exit 1; \
	done

lint-workflows: ## actionlint over .github/workflows
	@docker run --rm -v "$(CURDIR):/repo" -w /repo rhysd/actionlint:1.7.7

# --- Observability and on-call ------------------------------------------------------------------
# The obs stack is opt-in. `obs-up` starts it and recreates the app containers with the OTLP endpoint
# exported, because Compose passes environment at creation time; `obs-down` does the reverse and keeps
# the data volumes. Grafana is loopback-only and has no login: never tunnel it.

OBS := OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318
OBS_FILES := -f docker-compose.yml -f docker-compose.observability.yml --profile obs

obs-up: ## Start the opt-in observability stack and point the app at it (Grafana on 127.0.0.1:3001)
	$(OBS) $(COMPOSE) $(OBS_FILES) up -d
	$(OBS) $(COMPOSE) up -d --force-recreate backend mcp-server hermes oncall ingest
	@echo "Grafana: http://127.0.0.1:$${GRAFANA_PORT:-3001}  (anonymous viewer, loopback only)"
	@echo "Prometheus: docker compose exec -T prometheus wget -qO- http://127.0.0.1:9090/-/healthy"

obs-down: ## Stop the observability stack, keep its volumes, and turn app telemetry off again
	$(COMPOSE) $(OBS_FILES) down
	$(COMPOSE) up -d --force-recreate backend mcp-server hermes oncall ingest
	@echo "observability stopped; app containers recreated with telemetry off"

obs-logs: ## Tail one observability service: make obs-logs S=grafana
	$(COMPOSE) $(OBS_FILES) logs -f --tail=100 $(S)

telemetry-smoke: ## Probe the obs stack and count the exported series
	@curl -fsS http://127.0.0.1:$${GRAFANA_PORT:-3001}/api/health | head -c 200; echo
	@$(COMPOSE) $(OBS_FILES) exec -T prometheus wget -qO- http://127.0.0.1:9090/-/healthy; echo
	@echo "hermes series in Prometheus:"
	@$(COMPOSE) $(OBS_FILES) exec -T prometheus wget -qO- 'http://127.0.0.1:9090/api/v1/label/__name__/values' \
	  | tr ',' '\n' | grep -o 'hermes_[a-z_]*' | sort -u

oncall-report: ## Copy the on-call reports volume to data/oncall for inspection
	@mkdir -p data/oncall
	@docker compose cp oncall:/reports/. data/oncall/
	@ls -1 data/oncall

alert-check: ## Evaluate the ingest-health alert once against the real ledger
	@docker compose exec -T oncall python -m agent.oncall --once

alert-fire: ## Demonstrate the alert with a synthetic stale observation (no wait, no database)
	@docker compose exec -T oncall python -m agent.oncall --simulate stale

alert-drill: ## Real one-off evaluation with a 1-minute threshold against the live ledger
	@docker compose run --rm -e ONCALL_STALE_MINUTES=1 -e ONCALL_REQUIRED_BREACHES=1 \
	  oncall python -m agent.oncall --once

alert-state: ## Show the stored alert state
	@docker compose exec -T oncall cat /reports/alerts.json
