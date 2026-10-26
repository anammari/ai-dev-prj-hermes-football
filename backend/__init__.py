"""The read API, plus the one write a human makes: a review decision.

Two properties are deliberate, and both are worth stating before the code:

**`openapi.yaml` is the only definition of a response shape.** FastAPI's own schema generation is
switched off (`openapi_url=None`, `docs_url=None`) and `/openapi.yaml` serves the reviewed file
verbatim, so there is no second, generated spec that could drift from it. The handlers build plain
contract-shaped objects through `backend/schemas.py`; what makes them *typed* is
`tests/test_api_contract.py`, which validates every response against the contract, plus
`backend/contract.py`, which reads the contract at startup and takes the enums (`CompetitionCode`,
`MatchStatus`, `ReviewStatus`) from it instead of restating them in Python.

**Nothing here calls upstream, and the agent's data path is still read-only.** Every read goes through
`agent_readonly` (`AGENTS.md` rule 4); the only write the API can make is
`PATCH /admin/agent-turns/{id}/review`, through a separate `agent_admin` engine that may update the
two review columns and nothing else. The other declared `/admin` operation, the ingest trigger, stays
a documented `404` until the post-M6 queue: a request handler must not start an upstream run (rule 3).
"""

from __future__ import annotations

#: The API version, which is also the contract version. `tests/test_api_contract.py` fails when this
#: and `openapi.yaml`'s `info.version` disagree, so a contract change cannot ship half-applied.
__version__ = "0.4.1"

__all__ = ["__version__"]
