"""The M3 read API: FastAPI over the tables M1/M2 populate.

Two properties are deliberate, and both are worth stating before the code:

**`openapi.yaml` is the only definition of a response shape.** FastAPI's own schema generation is
switched off (`openapi_url=None`, `docs_url=None`) and `/openapi.yaml` serves the reviewed file
verbatim, so there is no second, generated spec that could drift from it. The handlers build plain
contract-shaped objects through `backend/schemas.py`; what makes them *typed* is
`tests/test_api_contract.py`, which validates every response against the contract, plus
`backend/contract.py`, which reads the contract at startup and takes the enums (`CompetitionCode`,
`MatchStatus`, `ReviewStatus`) from it instead of restating them in Python.

**This service never writes and never calls upstream.** Every request path reads through the
`agent_readonly` role when the deployment gives that role a password (`AGENTS.md` rule 4), and nothing
a request touches imports the ingest client (rule 3). That is also why the two `/admin` operations the
contract declares are not part of M3: the ingest trigger cannot be implemented without either calling
upstream from request-handling code or building a queue the ingest container drains, and the review
write is a dashboard feature. Both are declared, not hidden - see `backend/routers/admin.py`.
"""

from __future__ import annotations

#: The API version, which is also the contract version. `tests/test_api_contract.py` fails when this
#: and `openapi.yaml`'s `info.version` disagree, so a contract change cannot ship half-applied.
__version__ = "0.2.0"

__all__ = ["__version__"]
