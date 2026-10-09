# Hermes Football - developer entry points.
# Today only the contract tooling exists; the rest of the targets from
# _docs/product-spec.md land with the scaffold and must keep working once added.

SHELL := /bin/bash
SPEC  := openapi.yaml
SWAGGER_PORT ?= 8081
SWAGGER_NAME ?= hermes-football-swagger

.PHONY: help swagger swagger-stop validate-spec

help: ## Show available targets
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  %-16s %s\n", $$1, $$2}'

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
