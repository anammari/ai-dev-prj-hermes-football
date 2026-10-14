"""One module per group of contract paths.

Every route names its `operation_id` exactly as the contract does, because that is the identity
`tests/test_api_contract.py` matches on: a route whose operation id is not in the contract, or a
contract operation with no route, fails the suite. Handlers do three things and nothing else -
validate, call a service, attach `meta` - so the SQL stays in `backend/services/` and the shapes stay
in `backend/schemas.py`.

Each router carries `Depends(require_agent_token)` except the three operations the contract declares
with `security: []` (`backend/routers/open.py`), which are registered directly on the app.
"""
