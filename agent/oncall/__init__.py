"""The on-call agent: a daily data-quality digest and the one ingest-health alert.

It is an agent in the operational sense, not a model: every number in its output is a SQL count or a
stored eval metric. It reads through the `agent_readonly` role, never selects a message or an answer
column, never writes the database, never calls a model and never calls upstream. Its only writes are a
report file, an alert-state file, a log line and a metric.

`tests/test_oncall.py` and `tests/integration/test_oncall_stack.py` hold those bounds.
"""

from agent.oncall.config import OnCallSettings

__all__ = ["OnCallSettings"]
