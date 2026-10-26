# Application image: Python 3.12, the schema, the API, the corpus tooling and the tests.
#
# Deliberately one image for now, serving `backend`, the ingest scheduler and the tool targets from the
# same layers. M3 keeps it that way because the API and the scheduler share `db/` and `ingest/`
# wholesale; splitting a slim runtime image (no tests, no dev extras) is a follow-up, not something to
# half-do here. What must not change is that the image never contains a secret - everything arrives
# from `.env` at run time.

FROM python:3.12-slim AS app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencies first, as their own layer. pip itself is upgraded first: the base image's pip is a
# packaging tool, not a runtime dependency, but `pip-audit` reports its advisories too and a stale
# installer is not worth a permanent exception in the security baseline.
RUN pip install --no-cache-dir --upgrade pip

COPY pyproject.toml ./
COPY db ./db
COPY ingest ./ingest
COPY backend ./backend
COPY agent ./agent
COPY mcp_server ./mcp_server
COPY telemetry ./telemetry
RUN pip install --no-cache-dir ".[dev]"

# Then everything else, so editing a test or a note does not rebuild the dependency layer.
# openapi.yaml is an input to the test suite, not just a document: the contract-coverage test reads it.
COPY alembic.ini README.md openapi.yaml docker-compose.yml ./
COPY tests ./tests
COPY evals ./evals
COPY prompts ./prompts
COPY hermes ./hermes
# The capability table is read by `tests/test_capability_table.py`: the rule-7 register is a test
# input, so the image has to carry it.
COPY security ./security

RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /reports \
    && chown -R appuser:appuser /app /reports
USER appuser

# A bare `docker compose run tests` validates the corpus; the Makefile overrides this per target.
CMD ["python", "-m", "ingest.knowledge", "check"]
