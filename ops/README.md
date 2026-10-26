# Operations

Runbooks, incident evidence and the on-call agent's output. The code lives in `agent/oncall/`; the
alert rule is documented in [`../_docs/product-spec.md`](../_docs/product-spec.md) F10 and the
capability bounds in [`../security/capability-table.md`](../security/capability-table.md).

| File | When to read it |
| --- | --- |
| [`runbooks/on-call.md`](runbooks/on-call.md) | daily digest, alert checks, what the on-call container may read |
| [`runbooks/ingest-stale.md`](runbooks/ingest-stale.md) | the alert fired: triage, fix, verify |
| [`drills/2026-10-27-ingest-stale.md`](drills/2026-10-27-ingest-stale.md) | the recorded alert drill and its evidence |

The on-call container writes reports and `alerts.json` to the `oncall-reports` volume. Copy it out
with `make oncall-report`; never delete that volume as part of a cleanup (it is the digest history).
