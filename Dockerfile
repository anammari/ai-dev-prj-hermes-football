# Application image: Python 3.12, the schema, the corpus tooling and the tests.
#
# Deliberately one image for the tools for now. When `backend` and the ingest scheduler land they get
# their own stages (or their own images) rather than their own copies of this one; what must not
# change is that the image never contains a secret - everything arrives from `.env` at run time.

FROM python:3.12-slim AS app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencies first, as their own layer.
COPY pyproject.toml ./
COPY db ./db
COPY ingest ./ingest
RUN pip install --no-cache-dir ".[dev]"

# Then everything else, so editing a test or a note does not rebuild the dependency layer.
# openapi.yaml is an input to the test suite, not just a document: the contract-coverage test reads it.
COPY alembic.ini README.md openapi.yaml ./
COPY tests ./tests
COPY hermes ./hermes

RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app
USER appuser

# A bare `docker compose run tests` validates the corpus; the Makefile overrides this per target.
CMD ["python", "-m", "ingest.knowledge", "check"]
