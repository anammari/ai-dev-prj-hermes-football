# Pull request

## Goal

<!-- One paragraph: what behaviour or artifact changes, and why now. -->

## Acceptance criteria

<!-- Checkable statements, not a description. Prefer a command and an expected result. -->

- [ ]
- [ ]

## Out of scope

<!-- What this PR deliberately does not do. A recorded follow-up belongs in _docs/follow-ups.md. -->

## Verification

<!-- Paste the commands you ran and their result. CI cannot run these: `make eval`, the gateway
     integration test, the live Telegram smoke test. -->

```text
make test            # 411+ passed
make lint            # clean
make itest           # 41 passed, needs the stack and the local embedding model
make frontend-test   # 27 passed
make e2e             # 6 passed, needs make up
make eval-self-check # gate can fail
```

Local-only gates (CI cannot run them):

- [ ] `make itest` (real Ollama and Postgres)
- [ ] `make eval` / `make eval-self-check`
- [ ] live Telegram smoke test (owner)
- [ ] `make alert-drill` if the change touches alerting

## Policy

- [ ] `_docs/product-spec.md` updated in this PR if behaviour changed
- [ ] `_docs/permissions.md` has a row for every new capability or container
- [ ] `security/capability-table.md` updated
- [ ] `_docs/ai-usage-report.md` session entry added
- [ ] no secret, token, chat id or user message in the diff, logs or an image
- [ ] no new cloud egress path without an owner decision record

## Notes for the reviewer

<!-- Anything that is easy to get wrong, and the test that catches it. -->
